from __future__ import annotations

import logging
from datetime import datetime

from geoalchemy2.functions import ST_AsGeoJSON, ST_MakeEnvelope, ST_Within
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.location import Location
from app.models.post import Post

logger = logging.getLogger(__name__)

_HEATMAP_SECONDS_PER_DAY: float = 86400.0
_HEATMAP_DECAY_HALF_LIFE_DAYS: float = 14.0


class LocationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_map_locations(
        self,
        channel_id: int,
        min_confidence: float = 0.4,
        bbox: tuple[float, float, float, float] | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        geo_type: str | None = None,
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
            date_from: Optional lower bound for post_date (inclusive).
            date_to: Optional upper bound for post_date (inclusive).
            geo_type: Optional filter by location geo_type value.

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
                Post.cleaned_text.label("post_excerpt_raw"),
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

        if date_from is not None:
            stmt = stmt.where(Post.post_date >= date_from)

        if date_to is not None:
            stmt = stmt.where(Post.post_date <= date_to)

        if geo_type is not None:
            stmt = stmt.where(Location.geo_type == geo_type)

        result = await self._session.execute(stmt)
        rows = result.mappings().all()

        locations = [dict(row) for row in rows]
        logger.debug(
            "get_map_locations: returned %d locations for channel %d",
            len(locations),
            channel_id,
        )
        return locations

    async def get_heatmap_points(
        self,
        channel_id: int,
        min_confidence: float = 0.4,
        bbox: tuple[float, float, float, float] | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[tuple[float, float, float]]:
        """Return (lat, lng, weight) tuples for leaflet.heat.

        Weight formula: confidence * GREATEST(0.1, EXP(-(days_old / 14.0)))
        where days_old = seconds since post_date / 86400.
        Minimum weight 0.1 ensures old locations still appear faintly.
        """
        sql = f"""
            SELECT
                ST_Y(l.geometry) AS lat,
                ST_X(l.geometry) AS lng,
                l.confidence * GREATEST(0.1, EXP(
                    -(EXTRACT(EPOCH FROM (NOW() - COALESCE(p.post_date, NOW())))
                      / {_HEATMAP_SECONDS_PER_DAY} / {_HEATMAP_DECAY_HALF_LIFE_DAYS})
                )) AS weight
            FROM locations l
            JOIN posts p ON l.post_id = p.id
            WHERE p.channel_id = :channel_id
              AND p.is_deleted = false
              AND l.out_of_bounds = false
              AND l.confidence >= :min_confidence
        """
        params: dict[str, int | float | datetime] = {
            "channel_id": channel_id,
            "min_confidence": min_confidence,
        }

        if bbox is not None:
            west, south, east, north = bbox
            sql += " AND ST_Within(l.geometry, ST_MakeEnvelope(:west, :south, :east, :north, 4326))"
            params["west"] = west
            params["south"] = south
            params["east"] = east
            params["north"] = north

        if date_from is not None:
            sql += " AND p.post_date >= :date_from"
            params["date_from"] = date_from

        if date_to is not None:
            sql += " AND p.post_date <= :date_to"
            params["date_to"] = date_to

        result = await self._session.execute(text(sql), params)
        rows = result.all()

        points = [(float(row.lat), float(row.lng), float(row.weight)) for row in rows]
        logger.debug(
            "get_heatmap_points: returned %d points for channel %d",
            len(points),
            channel_id,
        )
        return points

    async def get_stats(
        self,
        channel_id: int,
        min_confidence: float = 0.4,
    ) -> dict[str, int | dict[str, int]]:
        """Return aggregate location counts for the public stats endpoint.

        Uses a single SQL query with FILTER clauses to compute all counts
        in one round-trip. Excludes deleted posts, out-of-bounds locations,
        and locations below min_confidence.

        Args:
            channel_id: Only count locations belonging to this channel's posts.
            min_confidence: Minimum confidence score (default 0.4).

        Returns:
            Dict with total, today, this_week, this_month, and by_geo_type counts.
        """
        sql = """
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE p.post_date >= NOW() - INTERVAL '1 day') AS today,
                COUNT(*) FILTER (WHERE p.post_date >= NOW() - INTERVAL '7 days') AS this_week,
                COUNT(*) FILTER (WHERE p.post_date >= NOW() - INTERVAL '30 days') AS this_month,
                COUNT(*) FILTER (WHERE l.geo_type = 'address') AS geo_address,
                COUNT(*) FILTER (WHERE l.geo_type = 'intersection') AS geo_intersection,
                COUNT(*) FILTER (WHERE l.geo_type = 'district') AS geo_district,
                COUNT(*) FILTER (WHERE l.geo_type = 'direction') AS geo_direction
            FROM locations l
            JOIN posts p ON l.post_id = p.id
            WHERE p.channel_id = :channel_id
              AND p.is_deleted = false
              AND l.out_of_bounds = false
              AND l.confidence >= :min_confidence
        """
        result = await self._session.execute(
            text(sql),
            {"channel_id": channel_id, "min_confidence": min_confidence},
        )
        row = result.one()
        logger.debug(
            "get_stats: total=%d for channel %d",
            row.total,
            channel_id,
        )
        return {
            "total": int(row.total),
            "today": int(row.today),
            "this_week": int(row.this_week),
            "this_month": int(row.this_month),
            "by_geo_type": {
                "address": int(row.geo_address),
                "intersection": int(row.geo_intersection),
                "district": int(row.geo_district),
                "direction": int(row.geo_direction),
            },
        }

    async def get_locations_near_line(
        self,
        geojson_line: str,
        radius_meters: float,
        channel_id: int,
        hours: int = 24,
        min_confidence: float = 0.4,
    ) -> list[dict[str, float | str | None]]:
        """Return danger locations within radius_meters of a route LineString.

        Uses geography cast for accurate meter-based distance calculation.

        Args:
            geojson_line: GeoJSON LineString as a JSON string.
            radius_meters: Buffer radius around the route in metres.
            channel_id: Only check locations belonging to this channel's posts.
            hours: Look back window in hours (default 24).
            min_confidence: Minimum confidence score (default 0.4).

        Returns:
            List of dicts: id, address, confidence, geo_type, lat, lng, post_date (ISO).
        """
        sql = """
            SELECT
                l.id,
                l.address,
                l.confidence,
                l.geo_type,
                ST_Y(l.geometry) AS lat,
                ST_X(l.geometry) AS lng,
                p.post_date
            FROM locations l
            JOIN posts p ON l.post_id = p.id
            WHERE p.channel_id = :channel_id
              AND p.is_deleted = false
              AND l.out_of_bounds = false
              AND l.confidence >= :min_confidence
              AND p.post_date >= NOW() - make_interval(hours => :hours)
              AND ST_DWithin(
                  l.geometry::geography,
                  ST_GeomFromGeoJSON(:line)::geography,
                  :radius
              )
        """
        result = await self._session.execute(
            text(sql),
            {
                "channel_id": channel_id,
                "min_confidence": min_confidence,
                "hours": hours,
                "line": geojson_line,
                "radius": radius_meters,
            },
        )
        rows = result.all()

        locations: list[dict[str, float | str | None]] = [
            {
                "id": row.id,
                "address": row.address,
                "confidence": float(row.confidence),
                "geo_type": row.geo_type,
                "lat": float(row.lat),
                "lng": float(row.lng),
                "post_date": row.post_date.isoformat() if row.post_date is not None else None,
            }
            for row in rows
        ]
        logger.debug(
            "get_locations_near_line: found %d locations within %.0fm for channel %d",
            len(locations),
            radius_meters,
            channel_id,
        )
        return locations

    async def bulk_save_locations(self, locations: list[Location]) -> int:
        """Add locations to session, flush, return count."""
        self._session.add_all(locations)
        await self._session.flush()
        logger.debug("bulk_save_locations: saved %d locations", len(locations))
        return len(locations)
