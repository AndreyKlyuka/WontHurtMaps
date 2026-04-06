from __future__ import annotations

import logging
from typing import TypedDict, cast

from geoalchemy2.functions import ST_AsGeoJSON
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.district import District

logger = logging.getLogger(__name__)


class DistrictFeatureRow(TypedDict):
    id: int
    name: str
    geojson: str


class DistrictRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_name(self, city_id: int, name: str) -> District | None:
        """Case-insensitive match against name and name_ru columns."""
        stmt = select(District).where(
            District.city_id == city_id,
            func.lower(District.name) == name.lower(),
        )
        result = await self._session.execute(stmt)
        entry = result.scalar_one_or_none()

        if entry is None:
            # Try name_ru as fallback
            stmt_ru = select(District).where(
                District.city_id == city_id,
                func.lower(District.name_ru) == name.lower(),
            )
            result_ru = await self._session.execute(stmt_ru)
            entry = result_ru.scalar_one_or_none()

        logger.debug(
            "district find_by_name: city_id=%d name=%r found=%s",
            city_id,
            name,
            entry is not None,
        )
        return entry

    async def get_geojson_features(self, city_id: int) -> list[DistrictFeatureRow]:
        """Return districts for city as raw dicts with GeoJSON geometry string."""
        stmt = select(
            District.id,
            District.name,
            ST_AsGeoJSON(District.polygon).label("geojson"),
        ).where(District.city_id == city_id)
        result = await self._session.execute(stmt)
        rows = result.mappings().all()
        logger.debug(
            "district get_geojson_features: city_id=%d count=%d",
            city_id,
            len(rows),
        )
        return [cast(DistrictFeatureRow, dict(row)) for row in rows]

    async def get_all(self, city_id: int) -> list[District]:
        """Return all districts for city (for LLM context and district fallback)."""
        stmt = select(District).where(District.city_id == city_id)
        result = await self._session.execute(stmt)
        districts = list(result.scalars().all())
        logger.debug(
            "district get_all: city_id=%d count=%d",
            city_id,
            len(districts),
        )
        return districts
