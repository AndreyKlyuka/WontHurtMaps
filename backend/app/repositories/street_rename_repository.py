from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.street_rename import StreetRename

logger = logging.getLogger(__name__)


class StreetRenameRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_active_renames(self, city_id: int) -> list[StreetRename]:
        """Return all renames where status='active'."""
        stmt = select(StreetRename).where(
            StreetRename.city_id == city_id,
            StreetRename.status == "active",
        )
        result = await self._session.execute(stmt)
        renames = list(result.scalars().all())
        logger.debug(
            "street_rename get_active_renames: city_id=%d count=%d",
            city_id,
            len(renames),
        )
        return renames
