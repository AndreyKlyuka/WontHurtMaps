from __future__ import annotations

import asyncio
import logging
import signal
import sys
import time
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import settings
from app.core.database import async_session_factory
from app.core.exceptions import TelegramAuthError
from app.repositories.advisory_lock import (
    PIPELINE_LOCK_ID,
    try_advisory_lock,
)
from app.repositories.channel_state_repository import ChannelStateRepository
from app.repositories.heartbeat_repository import HeartbeatRepository
from app.repositories.post_repository import PostRepository
from app.services.channel_resolver import ChannelResolverService
from app.services.deleted_posts_tracker import DeletedPostsTracker
from app.services.fetcher import FetcherService
from app.services.telegram_client import TelegramClientService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Single Telegram client instance — shared across all pipeline cycles so that
# the Telethon session and its event loop stay alive between runs.
_telegram_client = TelegramClientService()

scheduler = AsyncIOScheduler()


async def run_pipeline() -> None:
    """Full fetch pipeline cycle — called by APScheduler on each interval tick.

    Acquires a PostgreSQL advisory lock so that only one worker process runs
    the pipeline at a time. Skips the cycle silently if the lock is already held.

    Stages:
      1. Advisory lock
      2. Heartbeat: running
      3. Resolve channel (idle if none configured)
      4. Fetch new posts
      5. Bulk-save posts
      6. Update last_message_id on channel_state
      7. Check and mark deleted posts (non-critical)
      8. Heartbeat: idle with saved count
         (transaction-level lock auto-releases on commit)
    """
    start = time.monotonic()
    logger.info("Pipeline cycle started")

    try:
        await _execute_pipeline()
    except TelegramAuthError:
        logger.warning("Telegram auth failure during pipeline cycle — run scripts/telegram_auth.py to re-authenticate")
    except Exception:
        logger.exception("Pipeline cycle failed with unexpected error")
    finally:
        elapsed = time.monotonic() - start
        logger.info("Pipeline cycle finished in %.1fs", elapsed)


async def _execute_pipeline() -> None:
    """Inner pipeline logic wrapped in a DB session.

    Separated from run_pipeline() so that exception handling in the outer
    function remains clean and readable.
    """
    async with async_session_factory() as session:
        # --- 1. Advisory lock ---
        locked = await try_advisory_lock(session, PIPELINE_LOCK_ID)
        if not locked:
            logger.info("Pipeline lock held by another process — skipping cycle")
            return

        heartbeat_repo = HeartbeatRepository(session)

        # --- 2. Heartbeat: running ---
        await heartbeat_repo.upsert_heartbeat(status="running", current_job="fetch")
        await session.commit()

        # --- 3. Resolve channel ---
        resolver = ChannelResolverService(session, _telegram_client)
        channel = await resolver.resolve_channel()

        if channel is None:
            logger.warning("No channel configured or resolvable — entering idle mode")
            await heartbeat_repo.upsert_heartbeat(status="idle")
            await session.commit()
            return

        logger.info(
            "Channel resolved",
            extra={
                "channel_id": channel.channel_id,
                "channel_name": channel.channel_name,
                "last_message_id": channel.last_message_id,
            },
        )

        # --- 4. Fetch new posts ---
        fetcher = FetcherService(_telegram_client)
        posts = await fetcher.fetch_new_posts(
            channel_id=channel.channel_id,
            last_message_id=channel.last_message_id,
            city_id=channel.city_id,
        )

        logger.info(
            "Fetch complete",
            extra={"channel_id": channel.channel_id, "fetched_count": len(posts)},
        )

        saved_count = 0

        if posts:
            # --- 5. Bulk-save posts ---
            post_repo = PostRepository(session)
            saved_count = await post_repo.bulk_save_posts(posts)

            logger.info(
                "Posts saved",
                extra={
                    "channel_id": channel.channel_id,
                    "saved_count": saved_count,
                    "fetched_count": len(posts),
                },
            )

            # --- 6. Update last_message_id ---
            # Uses max from the fetched batch (not saved_count) so that already-existing
            # posts don't prevent the offset from advancing — correct idempotent behaviour.
            max_telegram_id = max(p["telegram_id"] for p in posts)
            channel_repo = ChannelStateRepository(session)
            await channel_repo.update_last_message_id(channel.id, max_telegram_id)

        # --- 7. Check and mark deleted posts (non-critical) ---
        # Runs unconditionally so that posts deleted during a quiet period
        # (no new messages fetched) are still caught and soft-deleted.
        # DeletedPostsTracker has its own early-exit when there are no stored posts.
        tracker = DeletedPostsTracker(_telegram_client, session)
        await tracker.check_and_mark_deleted(channel_id=channel.channel_id)

        await session.commit()

        # --- 8. Heartbeat: idle ---
        # Transaction-level advisory lock auto-releases on the commit below.
        # posts_processed reflects only newly saved posts — soft-deleted posts
        # from DeletedPostsTracker are not counted here.
        await heartbeat_repo.upsert_heartbeat(
            status="idle",
            current_job=None,
            posts_processed=saved_count,
        )
        await session.commit()


async def _startup() -> None:
    """Connect the Telegram client once before the scheduler starts ticking.

    A TelegramAuthError at this point is non-fatal: the scheduler still starts
    and pipeline cycles will fail fast (and log clearly) until the session is
    fixed. This allows the worker container to stay alive while an operator
    runs scripts/telegram_auth.py to obtain a fresh session.
    """
    try:
        await _telegram_client.connect()
        logger.info("Telegram client ready")
    except TelegramAuthError:
        logger.error(
            "Telegram auth failed at startup — pipeline cycles will be skipped "
            "until a valid session is present. Run scripts/telegram_auth.py to authenticate."
        )


async def _shutdown() -> None:
    """Stop APScheduler and disconnect the Telegram client."""
    logger.info("Shutting down scheduler")
    scheduler.shutdown(wait=False)
    await _telegram_client.disconnect()
    logger.info("Worker stopped")


async def _run_async() -> None:
    """Async entry point — startup, scheduler, signal handling, graceful shutdown."""
    await _startup()

    # Schedule the recurring pipeline job.
    scheduler.add_job(
        run_pipeline,
        "interval",
        minutes=settings.pipeline_interval_minutes,
        id="pipeline",
        max_instances=1,  # Safety net; advisory lock is the primary guard.
        misfire_grace_time=60,
    )

    # Run once immediately on startup so the first fetch does not wait a full
    # interval before producing data.
    scheduler.add_job(
        run_pipeline,
        id="pipeline_initial",
        next_run_time=datetime.now(UTC),
    )

    # AsyncIOScheduler.start() requires a running event loop — must be called
    # from within an async context.
    scheduler.start()

    logger.info(
        "WontHurtMaps Worker started, pipeline interval=%d min",
        settings.pipeline_interval_minutes,
    )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _handle_signal(signum: int, frame: object) -> None:
        logger.info("Received signal %d — initiating shutdown", signum)
        loop.call_soon_threadsafe(stop_event.set)

    signal.signal(signal.SIGINT, _handle_signal)
    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, _handle_signal)

    await stop_event.wait()
    await _shutdown()


def main() -> None:
    """Entry point."""
    asyncio.run(_run_async())


if __name__ == "__main__":
    main()
