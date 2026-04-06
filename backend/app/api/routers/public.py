from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_session
from app.core.limiter import limiter
from app.core.response_cache import response_cache
from app.repositories.channel_state_repository import ChannelStateRepository
from app.repositories.city_repository import CityRepository
from app.repositories.district_repository import DistrictRepository
from app.repositories.location_repository import LocationRepository

logger = logging.getLogger(__name__)

_POST_EXCERPT_LENGTH = 150

router = APIRouter(prefix="/api", tags=["public"])


def _parse_bbox(
    west: float | None,
    south: float | None,
    east: float | None,
    north: float | None,
) -> tuple[float, float, float, float] | None:
    """Parse and validate bbox query params.

    Raises HTTP 422 if 1-3 of 4 params are provided.
    Returns the bbox tuple or None if no params provided.
    """
    provided = sum(1 for v in (west, south, east, north) if v is not None)
    if provided not in (0, 4):
        raise HTTPException(
            status_code=422,
            detail="Provide all four bbox params (west, south, east, north) or none.",
        )
    if provided == 4:
        return (west, south, east, north)  # type: ignore[return-value]
    return None


SessionDep = Annotated[AsyncSession, Depends(get_session)]


class BboxSchema(BaseModel):
    north: float
    south: float
    east: float
    west: float


class CenterSchema(BaseModel):
    lat: float
    lng: float


class CityResponse(BaseModel):
    id: int
    name: str
    name_ru: str
    bbox: BboxSchema
    center: CenterSchema
    default_zoom: int


@router.get("/locations")
@limiter.limit("60/minute")
async def get_locations(
    request: Request,
    session: SessionDep,
    min_confidence: float = Query(default=0.4, ge=0.0, le=1.0),
    west: float | None = Query(default=None),
    south: float | None = Query(default=None),
    east: float | None = Query(default=None),
    north: float | None = Query(default=None),
    date_from: datetime | None = Query(default=None),  # noqa: B008
    date_to: datetime | None = Query(default=None),  # noqa: B008
    geo_type: str | None = Query(default=None),
) -> dict:
    """Return active danger locations for the public map.

    Locations from posts that were deleted in Telegram are excluded.
    Optionally filtered by bounding box (all four bbox params must be provided
    together), minimum confidence score, date range, and geo_type.

    Response shape:
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": { <GeoJSON Point> },
                    "properties": {
                        "id", "post_id", "address", "street_name",
                        "geo_type", "confidence", "resolved",
                        "resolved_by", "post_date", "post_excerpt"
                    }
                },
                ...
            ]
        }
    """
    cache_key = f"/api/locations:{sorted(request.query_params.items())}"
    cached = await response_cache.get(cache_key)
    if cached is not None:
        return cached

    bbox = _parse_bbox(west, south, east, north)

    channel_repo = ChannelStateRepository(session)
    channel = await channel_repo.get_active_channel()
    if channel is None:
        return {"type": "FeatureCollection", "features": []}

    location_repo = LocationRepository(session)
    locations = await location_repo.get_map_locations(
        channel_id=channel.channel_id,
        min_confidence=min_confidence,
        bbox=bbox,
        date_from=date_from,
        date_to=date_to,
        geo_type=geo_type,
    )

    features = [
        {
            "type": "Feature",
            "geometry": json.loads(loc["geojson"]),
            "properties": {
                "id": loc["id"],
                "post_id": loc["post_id"],
                "address": loc["address"],
                "street_name": loc["street_name"],
                "geo_type": loc["geo_type"],
                "confidence": loc["confidence"],
                "resolved": loc["resolved"],
                "resolved_by": loc["resolved_by"],
                "post_date": loc["post_date"].isoformat() if loc["post_date"] is not None else None,
                "post_excerpt": loc["post_excerpt_raw"][:_POST_EXCERPT_LENGTH]
                if loc["post_excerpt_raw"] is not None
                else None,
            },
        }
        for loc in locations
    ]

    result = {"type": "FeatureCollection", "features": features}
    await response_cache.set(cache_key, result, settings.api_cache_ttl_seconds)
    return result


@router.get("/heatmap")
@limiter.limit("60/minute")
async def get_heatmap(
    request: Request,
    session: SessionDep,
    min_confidence: float = Query(default=0.4, ge=0.0, le=1.0),
    west: float | None = Query(default=None),
    south: float | None = Query(default=None),
    east: float | None = Query(default=None),
    north: float | None = Query(default=None),
    date_from: datetime | None = Query(default=None),  # noqa: B008
    date_to: datetime | None = Query(default=None),  # noqa: B008
) -> dict:
    """Return heatmap points [[lat, lng, weight], ...] for leaflet.heat.

    Each point carries a time-decayed weight: confidence * EXP(-(days_old / 14)).
    Minimum weight is 0.1 so old locations still appear faintly.

    Response shape:
        {"points": [[lat, lng, weight], ...]}
    """
    cache_key = f"/api/heatmap:{sorted(request.query_params.items())}"
    cached = await response_cache.get(cache_key)
    if cached is not None:
        return cached

    bbox = _parse_bbox(west, south, east, north)

    channel_repo = ChannelStateRepository(session)
    channel = await channel_repo.get_active_channel()
    if channel is None:
        return {"points": []}

    location_repo = LocationRepository(session)
    points = await location_repo.get_heatmap_points(
        channel_id=channel.channel_id,
        min_confidence=min_confidence,
        bbox=bbox,
        date_from=date_from,
        date_to=date_to,
    )

    result = {"points": [list(p) for p in points]}
    await response_cache.set(cache_key, result, settings.api_cache_ttl_seconds)
    return result


_EMPTY_STATS: dict[str, int | dict[str, int]] = {
    "total": 0,
    "today": 0,
    "this_week": 0,
    "this_month": 0,
    "by_geo_type": {
        "address": 0,
        "intersection": 0,
        "district": 0,
        "direction": 0,
    },
}


@router.get("/stats")
@limiter.limit("60/minute")
async def get_stats(
    request: Request,
    session: SessionDep,
    min_confidence: float = Query(default=0.4, ge=0.0, le=1.0),
) -> dict[str, int | dict[str, int]]:
    """Return aggregate location counts for the public map stats panel.

    Response shape:
        {
            "total": int,
            "today": int,
            "this_week": int,
            "this_month": int,
            "by_geo_type": {
                "address": int,
                "intersection": int,
                "district": int,
                "direction": int
            }
        }
    """
    cache_key = f"/api/stats:{sorted(request.query_params.items())}"
    cached = await response_cache.get(cache_key)
    if cached is not None:
        return cached

    channel_repo = ChannelStateRepository(session)
    channel = await channel_repo.get_active_channel()
    if channel is None:
        return _EMPTY_STATS

    location_repo = LocationRepository(session)
    result = await location_repo.get_stats(
        channel_id=channel.channel_id,
        min_confidence=min_confidence,
    )
    await response_cache.set(cache_key, result, settings.api_cache_ttl_seconds)
    return result


@router.get("/cities", response_model=list[CityResponse])
@limiter.limit("60/minute")
async def get_cities(request: Request, session: SessionDep) -> list[CityResponse]:
    """Return all configured cities with bbox and center coordinates."""
    repo = CityRepository(session)
    cities = await repo.get_all()
    return [
        CityResponse(
            id=city.id,
            name=city.name,
            name_ru=city.name_ru,
            bbox=BboxSchema(
                north=city.bbox_north,
                south=city.bbox_south,
                east=city.bbox_east,
                west=city.bbox_west,
            ),
            center=CenterSchema(
                lat=(city.bbox_north + city.bbox_south) / 2,
                lng=(city.bbox_east + city.bbox_west) / 2,
            ),
            default_zoom=city.default_zoom,
        )
        for city in cities
    ]


@router.get("/districts")
@limiter.limit("60/minute")
async def get_districts(
    request: Request,
    session: SessionDep,
    city_id: int = Query(...),
) -> dict:
    """Return district polygons for a city as a GeoJSON FeatureCollection.

    Response shape:
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": { <GeoJSON Polygon> },
                    "properties": { "id": int, "name": str }
                },
                ...
            ]
        }
    """
    repo = DistrictRepository(session)
    rows = await repo.get_geojson_features(city_id)

    features = [
        {
            "type": "Feature",
            "geometry": json.loads(row["geojson"]),
            "properties": {
                "id": row["id"],
                "name": row["name"],
            },
        }
        for row in rows
    ]

    return {"type": "FeatureCollection", "features": features}
