from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.city import City

logger = logging.getLogger(__name__)


class CityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_all(self) -> list[City]:
        result = await self._session.execute(select(City))
        return list(result.scalars().all())
