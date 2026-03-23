from __future__ import annotations

import logging

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChannelState

logger = logging.getLogger(__name__)


class ChannelStateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_active_channel(self, city_id: int | None = None) -> ChannelState | None:
        """Get active channel. If city_id given, filter by it.

        Returns first active channel or None.
        """
        stmt = select(ChannelState).where(ChannelState.is_active.is_(True))
        if city_id is not None:
            stmt = stmt.where(ChannelState.city_id == city_id)

        result = await self._session.execute(stmt)
        channel = result.scalars().first()
        logger.debug(
            "get_active_channel: city_id=%s found=%s",
            city_id,
            channel is not None,
        )
        return channel

    async def update_last_message_id(self, channel_state_id: int, last_message_id: int) -> None:
        """Update last_message_id for given channel's DB record."""
        stmt = update(ChannelState).where(ChannelState.id == channel_state_id).values(last_message_id=last_message_id)
        await self._session.execute(stmt)
        await self._session.flush()
        logger.debug(
            "update_last_message_id: channel_state.id=%d last_message_id=%d",
            channel_state_id,
            last_message_id,
        )
