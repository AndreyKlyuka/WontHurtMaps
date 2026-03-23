from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.repositories.channel_state_repository import ChannelStateRepository
from app.repositories.location_repository import LocationRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["public"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/locations")
async def get_locations(
    session: SessionDep,
    min_confidence: float = Query(default=0.4, ge=0.0, le=1.0),
    west: float | None = Query(default=None),
    south: float | None = Query(default=None),
    east: float | None = Query(default=None),
    north: float | None = Query(default=None),
) -> dict:
    """Return active danger locations for the public map.

    Locations from posts that were deleted in Telegram are excluded.
    Optionally filtered by bounding box (all four bbox params must be provided
    together) and minimum confidence score.

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
                        "resolved_by", "post_date"
                    }
                },
                ...
            ]
        }
    """
    bbox: tuple[float, float, float, float] | None = None
    if all(v is not None for v in (west, south, east, north)):
        bbox = (west, south, east, north)  # type: ignore[arg-type]

    channel_repo = ChannelStateRepository(session)
    channel = await channel_repo.get_active_channel()
    if channel is None:
        return {"type": "FeatureCollection", "features": []}

    location_repo = LocationRepository(session)
    locations = await location_repo.get_map_locations(
        channel_id=channel.channel_id,
        min_confidence=min_confidence,
        bbox=bbox,
    )

    features = [
        {
            "type": "Feature",
            "geometry": loc["geojson"],
            "properties": {
                "id": loc["id"],
                "post_id": loc["post_id"],
                "address": loc["address"],
                "street_name": loc["street_name"],
                "geo_type": loc["geo_type"],
                "confidence": loc["confidence"],
                "resolved": loc["resolved"],
                "resolved_by": loc["resolved_by"],
                "post_date": loc["post_date"].isoformat() if loc["post_date"] else None,
            },
        }
        for loc in locations
    ]

    return {"type": "FeatureCollection", "features": features}
