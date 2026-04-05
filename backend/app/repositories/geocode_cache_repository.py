from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.geocode_cache import GeocodeCache

logger = logging.getLogger(__name__)

_CACHE_TTL_DAYS = 90


class GeocodeCacheRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lookup(self, city_id: int, query: str) -> GeocodeCache | None:
        """Find cached geocode result. Increment hit_count on hit. Skip expired entries."""
        now = datetime.now(UTC)
        stmt = select(GeocodeCache).where(
            GeocodeCache.city_id == city_id,
            GeocodeCache.query == query,
            GeocodeCache.expires_at > now,
        )
        result = await self._session.execute(stmt)
        entry = result.scalar_one_or_none()

        if entry is not None:
            entry.hit_count += 1
            await self._session.flush()
            logger.debug(
                "geocode_cache hit: city_id=%d query=%r hit_count=%d",
                city_id,
                query,
                entry.hit_count,
            )

        return entry

    async def save(
        self,
        city_id: int,
        query: str,
        lat: float,
        lng: float,
        result_type: str,
    ) -> GeocodeCache:
        """Insert or update cache entry. Set expires_at = now + 90 days."""
        now = datetime.now(UTC)
        expires_at = now + timedelta(days=_CACHE_TTL_DAYS)

        stmt = (
            insert(GeocodeCache)
            .values(
                city_id=city_id,
                query=query,
                result_lat=lat,
                result_lng=lng,
                result_type=result_type,
                expires_at=expires_at,
                hit_count=0,
            )
            .on_conflict_do_update(
                constraint="uq_geocode_cache_city_query",
                set_={
                    "result_lat": lat,
                    "result_lng": lng,
                    "result_type": result_type,
                    "expires_at": expires_at,
                    "hit_count": 0,
                },
            )
            .returning(GeocodeCache)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()

        entry = result.scalar_one()
        logger.debug(
            "geocode_cache saved: city_id=%d query=%r expires_at=%s",
            city_id,
            query,
            expires_at.isoformat(),
        )
        return entry
