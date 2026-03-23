from __future__ import annotations

import logging

from telethon import TelegramClient

from app.core.config import settings
from app.core.exceptions import TelegramAuthError

logger = logging.getLogger(__name__)


class TelegramClientService:
    """Wrapper around Telethon TelegramClient for the worker process.

    Lifecycle is managed explicitly: call connect() before use and
    disconnect() on shutdown. No retry logic lives here — that belongs
    in the worker that calls this service.
    """

    def __init__(self) -> None:
        self._client: TelegramClient | None = None

    async def connect(self) -> None:
        """Create a Telethon session and verify the user is authorized.

        Raises:
            TelegramAuthError: if the session is not authorized or the
                underlying transport raises OSError / ConnectionError.
        """
        session_path = settings.telegram_session_path_resolved
        try:
            self._client = TelegramClient(
                str(session_path),
                settings.telegram_api_id,
                settings.telegram_api_hash,
            )
            await self._client.connect()
        except (OSError, ConnectionError) as exc:
            logger.error(
                "Failed to establish Telegram connection",
                extra={"session_path": str(session_path)},
            )
            raise TelegramAuthError("connection failed") from exc

        if not await self._client.is_user_authorized():
            logger.error(
                "Telegram session exists but user is not authorized — run scripts/telegram_auth.py to authenticate",
                extra={"session_path": str(session_path)},
            )
            raise TelegramAuthError("session not authorized")

        logger.info(
            "Telegram client connected and authorized",
            extra={"session_path": str(session_path)},
        )

    async def disconnect(self) -> None:
        """Gracefully close the Telethon session.

        Safe to call even if connect() was never called or already
        disconnected — returns silently in both cases.
        """
        if self._client is None or not self._client.is_connected():
            return

        await self._client.disconnect()
        self._client = None
        logger.info("Telegram client disconnected")

    @property
    def client(self) -> TelegramClient:
        """Return the underlying TelegramClient.

        Raises:
            RuntimeError: if called before connect() succeeds.
        """
        if self._client is None:
            raise RuntimeError("TelegramClientService not connected")
        return self._client

    @property
    def is_connected(self) -> bool:
        """True when the client exists and the transport is open."""
        return self._client is not None and self._client.is_connected()
