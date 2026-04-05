from __future__ import annotations

import logging

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Post

logger = logging.getLogger(__name__)


class PostRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def bulk_save_posts(self, posts: list[dict]) -> int:
        """Bulk insert posts with deduplication by telegram_id.

        Uses INSERT ... ON CONFLICT (telegram_id) DO NOTHING.
        Returns count of actually inserted rows.
        """
        if not posts:
            return 0

        stmt = insert(Post).values(posts).on_conflict_do_nothing(index_elements=["telegram_id"])
        result = await self._session.execute(stmt)
        await self._session.flush()

        inserted: int = result.rowcount  # type: ignore[attr-defined]
        logger.debug("bulk_save_posts: inserted %d of %d posts", inserted, len(posts))
        return inserted

    async def mark_deleted(self, telegram_ids: list[int]) -> int:
        """Soft-delete posts by telegram_ids. Set is_deleted=True.

        Returns count of updated rows.
        """
        if not telegram_ids:
            return 0

        stmt = update(Post).where(Post.telegram_id.in_(telegram_ids)).values(is_deleted=True)
        result = await self._session.execute(stmt)
        await self._session.flush()

        updated: int = result.rowcount  # type: ignore[attr-defined]
        logger.debug("mark_deleted: soft-deleted %d posts", updated)
        return updated

    async def get_active_telegram_ids(self, channel_id: int, limit: int = 500) -> list[int]:
        """Return telegram_ids of stored posts that are not yet marked deleted.

        Used by DeletedPostsTracker to check previously saved posts against
        the live Telegram channel. Ordered by post_date DESC so recent posts
        (more likely to be deleted) are checked first.
        """
        stmt = (
            select(Post.telegram_id)
            .where(
                Post.channel_id == channel_id,
                Post.is_deleted.is_(False),
            )
            .order_by(Post.post_date.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        ids = list(result.scalars().all())
        logger.debug(
            "get_active_telegram_ids: found %d active posts for channel %d",
            len(ids),
            channel_id,
        )
        return ids

    async def get_deleted_posts(self, channel_id: int, page: int = 1, limit: int = 50) -> tuple[list[Post], int]:
        """Return paginated soft-deleted posts with their locations eagerly loaded.

        Returns a tuple of (posts, total_count).
        """
        offset = (page - 1) * limit

        count_stmt = (
            select(func.count()).select_from(Post).where(Post.channel_id == channel_id, Post.is_deleted.is_(True))
        )
        total = (await self._session.execute(count_stmt)).scalar_one()

        stmt = (
            select(Post)
            .options(selectinload(Post.locations))
            .where(Post.channel_id == channel_id, Post.is_deleted.is_(True))
            .order_by(Post.post_date.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        posts = list(result.scalars().all())
        return posts, total

    async def get_pending_posts(self, limit: int = 100) -> list[Post]:
        """Fetch posts with status='pending', ordered by post_date.

        Interface for Phase 2 pipeline.
        """
        stmt = (
            select(Post)
            .where(Post.status == "pending", Post.is_deleted.is_(False))
            .order_by(Post.post_date)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        posts = list(result.scalars().all())
        logger.debug("get_pending_posts: fetched %d posts (limit=%d)", len(posts), limit)
        return posts

    async def update_post_status(
        self,
        post_id: int,
        status: str,
        error_message: str | None = None,
    ) -> None:
        """Update post status. Increment retry_count if status is 'failed'."""
        values: dict = {"status": status, "error_message": error_message}
        if status == "failed":
            values["retry_count"] = Post.retry_count + 1

        stmt = update(Post).where(Post.id == post_id).values(**values)
        await self._session.execute(stmt)
        await self._session.flush()
        logger.debug(
            "update_post_status: post_id=%d status=%r",
            post_id,
            status,
        )

    async def get_retryable_posts(self, limit: int = 100) -> list[Post]:
        """Fetch posts with status='failed' and retry_count < 3."""
        stmt = (
            select(Post)
            .where(
                Post.status == "failed",
                Post.retry_count < 3,
                Post.is_deleted.is_(False),
            )
            .order_by(Post.post_date)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        posts = list(result.scalars().all())
        logger.debug(
            "get_retryable_posts: fetched %d posts (limit=%d)",
            len(posts),
            limit,
        )
        return posts
