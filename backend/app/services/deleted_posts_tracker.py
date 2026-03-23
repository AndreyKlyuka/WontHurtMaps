from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.post_repository import PostRepository
from app.services.telegram_client import TelegramClientService

logger = logging.getLogger(__name__)

# Telethon's get_messages() accepts at most 100 IDs per call.
_BATCH_SIZE = 100

# How many stored posts to check per pipeline cycle.
# Recent posts are checked first (ordered by post_date DESC in the repository).
_CHECK_LIMIT = 500


class DeletedPostsTracker:
    """Checks whether previously stored Telegram messages still exist in the channel.

    Each pipeline cycle the tracker queries the DB for up to _CHECK_LIMIT active
    (not yet deleted) post IDs, then verifies them against the live Telegram
    channel via get_messages(). Any ID that comes back as None is soft-deleted
    in the DB (is_deleted=True). The post data is preserved so that the admin
    can still access raw_text and location information for audit purposes.

    Posts marked as deleted are excluded from the public map but remain visible
    in the admin panel under GET /api/admin/posts/deleted.
    """

    def __init__(self, telegram_client: TelegramClientService, session: AsyncSession) -> None:
        self._telegram = telegram_client
        self._session = session

    async def check_and_mark_deleted(self, channel_id: int) -> int:
        """Check stored posts for deletion and mark any removed ones.

        Fetches up to _CHECK_LIMIT previously stored telegram_ids from the DB,
        verifies each against Telegram, and soft-deletes those that are gone.

        Args:
            channel_id: Numeric Telegram channel ID to query.

        Returns:
            Count of posts newly marked as deleted in the database.
        """
        repo = PostRepository(self._session)
        stored_ids = await repo.get_active_telegram_ids(channel_id, limit=_CHECK_LIMIT)

        if not stored_ids:
            return 0

        deleted_ids: list[int] = []

        try:
            deleted_ids = await self._find_deleted_ids(channel_id, stored_ids)
        except Exception:
            logger.warning(
                "Failed to check deleted messages — skipping deletion detection for this cycle",
                extra={"channel_id": channel_id, "checked_count": len(stored_ids)},
                exc_info=True,
            )
            return 0

        if not deleted_ids:
            return 0

        marked = await repo.mark_deleted(deleted_ids)
        logger.info(
            "Marked deleted posts",
            extra={
                "channel_id": channel_id,
                "deleted_count": marked,
                "checked_count": len(stored_ids),
            },
        )
        return marked

    async def _find_deleted_ids(self, channel_id: int, telegram_ids: list[int]) -> list[int]:
        """Batch-query Telegram and return IDs whose messages came back as None."""
        client = self._telegram.client
        deleted: list[int] = []

        for batch_start in range(0, len(telegram_ids), _BATCH_SIZE):
            batch = telegram_ids[batch_start : batch_start + _BATCH_SIZE]

            # get_messages returns a list aligned with the requested IDs;
            # a None entry means the message no longer exists.
            messages = await client.get_messages(channel_id, ids=batch)

            # Telethon may return a single object instead of a list when only
            # one ID is requested, so normalise to a list.
            if not isinstance(messages, list):
                messages = [messages]

            for msg_id, msg in zip(batch, messages, strict=True):
                if msg is None:
                    deleted.append(msg_id)

        return deleted
