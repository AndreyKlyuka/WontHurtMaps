from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from telethon.errors import FloodWaitError

from app.core.config import settings
from app.services.telegram_client import TelegramClientService

if TYPE_CHECKING:
    from telethon.tl.types import Message

logger = logging.getLogger(__name__)

# Exponential backoff base delay in seconds for network errors.
_BACKOFF_BASE_SECONDS = 5
_MAX_RETRIES = 3
# Maximum flood wait we are willing to sleep inline. If Telegram requests a longer
# wait the pipeline cycle exits early (releasing the advisory lock) and the next
# scheduled cycle will retry after the normal interval.
_MAX_FLOOD_WAIT_SECONDS = 300


class FetcherService:
    """Fetches new posts from a Telegram channel incrementally.

    Handles FloodWaitError and transient network failures with retry/backoff.
    Does not perform any DB operations — returns raw dicts for the caller to persist.
    """

    def __init__(self, telegram_client: TelegramClientService) -> None:
        self._telegram = telegram_client

    async def fetch_new_posts(
        self,
        channel_id: int,
        last_message_id: int,
        city_id: int,
    ) -> list[dict]:
        """Fetch new messages from a Telegram channel since last_message_id.

        Bootstrap mode (last_message_id == 0): fetches the last
        `settings.telegram_bootstrap_limit` messages.
        Incremental mode: fetches only messages with id > last_message_id.

        Returns a list of post dicts sorted by telegram_id ascending (oldest
        first), ready for PostRepository.bulk_save_posts().

        On permanent failure after retries the partial result collected so far
        is returned rather than raising, so the pipeline can make progress.
        """
        collected: list[dict] = []

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                collected = await self._fetch_with_flood_retry(channel_id, last_message_id, city_id)
                break  # success — exit retry loop

            except FloodWaitError as exc:
                # _fetch_with_flood_retry only re-raises when wait > _MAX_FLOOD_WAIT_SECONDS.
                # Return whatever was collected before this cycle started (empty on first attempt).
                logger.error(
                    "Telegram FloodWaitError exceeds limit — aborting cycle, returning partial results",
                    extra={
                        "wait_seconds": exc.seconds,
                        "limit_seconds": _MAX_FLOOD_WAIT_SECONDS,
                        "channel_id": channel_id,
                        "collected_so_far": len(collected),
                    },
                )
                break

            except (ConnectionError, OSError) as exc:
                wait_time = _BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))  # 5, 10, 20
                logger.warning(
                    "Network error fetching Telegram messages — will retry",
                    extra={
                        "attempt": attempt,
                        "wait_time": wait_time,
                        "error": str(exc),
                        "channel_id": channel_id,
                    },
                )
                if attempt == _MAX_RETRIES:
                    logger.error(
                        "Permanent failure fetching Telegram messages after %d retries — returning partial results",
                        _MAX_RETRIES,
                        extra={"channel_id": channel_id, "collected_so_far": len(collected)},
                    )
                    break
                await asyncio.sleep(wait_time)

        return sorted(collected, key=lambda p: p["telegram_id"])

    async def _fetch_with_flood_retry(
        self,
        channel_id: int,
        last_message_id: int,
        city_id: int,
    ) -> list[dict]:
        """Run _iter_messages, sleeping on FloodWaitError until Telegram allows the request.

        FloodWait is not a transient failure — sleeping the required duration always
        satisfies Telegram's rate limit, so this loop retries unconditionally.
        Network errors (ConnectionError, OSError) propagate to the outer retry loop.
        """
        while True:
            try:
                return await self._iter_messages(channel_id, last_message_id, city_id)
            except FloodWaitError as exc:
                wait = exc.seconds
                if wait > _MAX_FLOOD_WAIT_SECONDS:
                    logger.error(
                        "Telegram FloodWaitError exceeds limit — aborting cycle",
                        extra={
                            "wait_seconds": wait,
                            "limit_seconds": _MAX_FLOOD_WAIT_SECONDS,
                            "channel_id": channel_id,
                        },
                    )
                    raise
                logger.warning(
                    "Telegram FloodWaitError — sleeping before retry",
                    extra={"wait_seconds": wait, "channel_id": channel_id},
                )
                await asyncio.sleep(wait)

    async def _iter_messages(
        self,
        channel_id: int,
        last_message_id: int,
        city_id: int,
    ) -> list[dict]:
        """Run a single Telethon iter_messages pass and map results to dicts.

        Bootstrap: limit=telegram_bootstrap_limit, no min_id filter.
        Incremental: no limit, min_id=last_message_id so only newer IDs come back.
        """
        client = self._telegram.client
        posts: list[dict] = []

        is_bootstrap = last_message_id == 0

        if is_bootstrap:
            iterator = client.iter_messages(
                channel_id,
                limit=settings.telegram_bootstrap_limit,
            )
            logger.info(
                "Bootstrap fetch: requesting last %d messages",
                settings.telegram_bootstrap_limit,
                extra={"channel_id": channel_id},
            )
        else:
            # min_id is exclusive — Telethon returns messages with id > min_id.
            iterator = client.iter_messages(
                channel_id,
                min_id=last_message_id,
                limit=None,
            )
            logger.info(
                "Incremental fetch: requesting messages after id=%d",
                last_message_id,
                extra={"channel_id": channel_id},
            )

        message: Message
        async for message in iterator:
            # Skip media-only and service messages that carry no text.
            if not message.text:
                continue

            posts.append(
                {
                    "telegram_id": message.id,
                    "channel_id": channel_id,
                    "raw_text": message.text.split("\n\n")[0].strip(),
                    "post_date": message.date,  # timezone-aware datetime from Telethon
                    "city_id": city_id,
                    "status": "pending",
                }
            )

        logger.info(
            "Fetched %d text messages from channel",
            len(posts),
            extra={"channel_id": channel_id, "bootstrap": is_bootstrap},
        )
        return posts
