from __future__ import annotations

import logging

from geoalchemy2.functions import ST_AsGeoJSON, ST_MakeEnvelope, ST_Within
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.location import Location
from app.models.post import Post

logger = logging.getLogger(__name__)


class LocationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_map_locations(
        self,
        channel_id: int,
        min_confidence: float = 0.4,
        bbox: tuple[float, float, float, float] | None = None,
    ) -> list[dict]:
        """Return active locations for the public map.

        Filters out:
        - Locations whose post has is_deleted=True (removed from Telegram)
        - Locations with out_of_bounds=True (geocoder returned result outside city)
        - Locations below min_confidence threshold

        Args:
            channel_id: Only return locations belonging to this channel's posts.
            min_confidence: Minimum confidence score (default 0.4 — review threshold).
            bbox: Optional (west, south, east, north) bounding box for spatial filter.

        Returns:
            List of dicts with location data including GeoJSON geometry.
        """
        stmt = (
            select(
                Location.id,
                Location.post_id,
                Location.address,
                Location.street_name,
                Location.geo_type,
                Location.confidence,
                Location.resolved,
                Location.resolved_by,
                Post.post_date,
                ST_AsGeoJSON(Location.geometry).label("geojson"),
            )
            .join(Post, Location.post_id == Post.id)
            .where(
                Post.channel_id == channel_id,
                Post.is_deleted.is_(False),
                Location.out_of_bounds.is_(False),
                Location.confidence >= min_confidence,
            )
        )

        if bbox is not None:
            west, south, east, north = bbox
            stmt = stmt.where(ST_Within(Location.geometry, ST_MakeEnvelope(west, south, east, north, 4326)))

        result = await self._session.execute(stmt)
        rows = result.mappings().all()

        locations = [dict(row) for row in rows]
        logger.debug(
            "get_map_locations: returned %d locations for channel %d",
            len(locations),
            channel_id,
        )
        return locations

    async def bulk_save_locations(self, locations: list[Location]) -> int:
        """Add locations to session, flush, return count."""
        self._session.add_all(locations)
        await self._session.flush()
        logger.debug("bulk_save_locations: saved %d locations", len(locations))
        return len(locations)
