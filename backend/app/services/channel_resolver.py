from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from telethon.tl.types import Channel, Chat

from app.core.config import settings
from app.models import ChannelState
from app.repositories.channel_state_repository import ChannelStateRepository
from app.services.telegram_client import TelegramClientService

logger = logging.getLogger(__name__)

# City ID for Odesa — the sole target city in the MVP.
_ODESA_CITY_ID = 1

# TODO: remove hardcode when admin panel channel management is implemented
_FALLBACK_CHANNEL_NAME = "Не повредит, Одесса"


class ChannelResolverService:
    """Resolves the active Telegram channel that the worker should fetch from.

    Resolution priority:
    1. Active channel row in DB (channel_state.is_active = True).
    2. Env override: settings.telegram_channel_name — searched via iter_dialogs(),
       persisted as a new channel_state row, then returned.
    3. Hardcoded fallback: _FALLBACK_CHANNEL_NAME — same search/persist flow.
    4. None — caller enters idle mode.
    """

    def __init__(
        self,
        session: AsyncSession,
        telegram_client: TelegramClientService,
    ) -> None:
        self._session = session
        self._telegram_client = telegram_client
        self._repo = ChannelStateRepository(session)

    async def resolve_channel(self) -> ChannelState | None:
        """Return the channel to fetch from, or None if none is available.

        See class docstring for resolution priority.
        """
        # 1. DB-configured active channel (fast path).
        channel = await self._repo.get_active_channel()
        if channel is not None:
            logger.info(
                "Resolved channel from DB: '%s' (id=%d)",
                channel.channel_name,
                channel.channel_id,
            )
            return channel

        # 2. Env override.
        env_name = settings.telegram_channel_name.strip()
        if env_name:
            logger.info("No active channel in DB — trying env override: '%s'", env_name)
            return await self._resolve_by_name(env_name)

        # 3. Hardcoded fallback.
        logger.info("No env override — trying hardcoded fallback: '%s'", _FALLBACK_CHANNEL_NAME)
        return await self._resolve_by_name(_FALLBACK_CHANNEL_NAME)

    async def _resolve_by_name(self, name: str) -> ChannelState | None:
        """Iterate account dialogs to find a channel matching the given title."""
        async for dialog in self._telegram_client.client.iter_dialogs():
            title = getattr(dialog.entity, "title", None)
            if title and title.lower() == name.lower():
                return await self._persist_channel(dialog.entity, name)
        logger.warning(
            "Channel '%s' not found in dialogs",
            name,
            extra={"channel_name": name},
        )
        return None

    async def _persist_channel(self, entity: Channel | Chat, name: str) -> ChannelState:
        """Persist a newly resolved channel entity as a ChannelState row and return it."""
        channel_id: int = entity.id
        channel_title: str | None = getattr(entity, "title", None)

        new_channel = ChannelState(
            city_id=_ODESA_CITY_ID,
            channel_id=channel_id,
            channel_name=name,
            channel_title=channel_title,
            is_active=True,
            last_message_id=0,
        )
        try:
            # Use a savepoint so that an IntegrityError from a concurrent insert
            # rolls back only this operation, not the entire transaction.
            async with self._session.begin_nested():
                self._session.add(new_channel)
                await self._session.flush()
            await self._session.refresh(new_channel)
        except IntegrityError:
            logger.info(
                "Channel '%s' already persisted by concurrent process — fetching existing row",
                name,
                extra={"channel_name": name, "channel_id": channel_id},
            )
            existing = await self._repo.get_active_channel()
            if existing is not None:
                return existing
            raise

        logger.info(
            "Persisted channel: '%s' (channel_id=%d, db_id=%d)",
            name,
            channel_id,
            new_channel.id,
            extra={"channel_name": name, "channel_id": channel_id},
        )
        return new_channel
