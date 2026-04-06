from __future__ import annotations

import json
import logging
from typing import Annotated, TypedDict

import httpx
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_session
from app.core.exceptions import AppError
from app.core.limiter import limiter
from app.repositories.channel_state_repository import ChannelStateRepository
from app.repositories.location_repository import LocationRepository

logger = logging.getLogger(__name__)


class _DangerLocation(TypedDict):
    id: int
    address: str
    confidence: float
    geo_type: str
    lat: float
    lng: float
    post_date: str | None


class RouteCheckResponse(TypedDict):
    route: dict[str, object]
    danger_locations: list[_DangerLocation]
    danger_count: int


router = APIRouter(prefix="/api", tags=["public"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

_OSRM_TIMEOUT_SECONDS = 10.0


@router.get("/route/check")
@limiter.limit("60/minute")
async def check_route(
    request: Request,
    session: SessionDep,
    origin_lat: float = Query(..., ge=-90, le=90),
    origin_lng: float = Query(..., ge=-180, le=180),
    dest_lat: float = Query(..., ge=-90, le=90),
    dest_lng: float = Query(..., ge=-180, le=180),
    radius_meters: float = Query(default=100.0, ge=10, le=500),
    hours: int = Query(default=24, ge=1, le=168),
    min_confidence: float = Query(default=0.4, ge=0.0, le=1.0),
) -> RouteCheckResponse:
    """Check a route for nearby danger locations.

    Calls OSRM to get the route polyline, then queries PostGIS for
    danger locations within radius_meters of the route.

    Response:
        {
            "route": { "type": "LineString", "coordinates": [[lng, lat], ...] },
            "danger_locations": [...],
            "danger_count": int
        }
    """
    route_geometry = await _fetch_osrm_route(origin_lat, origin_lng, dest_lat, dest_lng)

    channel_repo = ChannelStateRepository(session)
    channel = await channel_repo.get_active_channel()
    if channel is None:
        return {
            "route": route_geometry,
            "danger_locations": [],
            "danger_count": 0,
        }

    geojson_line = json.dumps(route_geometry)

    location_repo = LocationRepository(session)
    danger_locations = await location_repo.get_locations_near_line(
        geojson_line=geojson_line,
        radius_meters=radius_meters,
        channel_id=channel.channel_id,
        hours=hours,
        min_confidence=min_confidence,
    )

    return {
        "route": route_geometry,
        "danger_locations": danger_locations,
        "danger_count": len(danger_locations),
    }


async def _fetch_osrm_route(
    origin_lat: float,
    origin_lng: float,
    dest_lat: float,
    dest_lng: float,
) -> dict:
    """Call OSRM routing API and return the GeoJSON LineString geometry.

    Raises AppError(503) on timeout, HTTP error, or unexpected response shape.
    """
    osrm_url = (
        f"{settings.osrm_url}/route/v1/driving/"
        f"{origin_lng},{origin_lat};{dest_lng},{dest_lat}"
        "?geometries=geojson&overview=full"
    )

    try:
        async with httpx.AsyncClient(timeout=_OSRM_TIMEOUT_SECONDS) as client:
            response = await client.get(osrm_url)
            response.raise_for_status()
            data = response.json()
    except httpx.TimeoutException as exc:
        logger.warning("OSRM request timed out: %s", osrm_url)
        raise AppError(
            message="Route service unavailable",
            code="ROUTE_SERVICE_UNAVAILABLE",
            status=503,
        ) from exc
    except httpx.HTTPStatusError as exc:
        logger.warning("OSRM HTTP error %d: %s", exc.response.status_code, osrm_url)
        raise AppError(
            message="Route service unavailable",
            code="ROUTE_SERVICE_UNAVAILABLE",
            status=503,
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected error calling OSRM: %s", osrm_url)
        raise AppError(
            message="Route service unavailable",
            code="ROUTE_SERVICE_UNAVAILABLE",
            status=503,
        ) from exc

    try:
        geometry: dict = data["routes"][0]["geometry"]
    except (KeyError, IndexError, TypeError) as exc:
        logger.warning("Unexpected OSRM response structure: %s", data)
        raise AppError(
            message="Route service unavailable",
            code="ROUTE_SERVICE_UNAVAILABLE",
            status=503,
        ) from exc

    return geometry
