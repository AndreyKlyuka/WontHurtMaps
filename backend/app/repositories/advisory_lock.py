from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Lock ID reserved for the hourly pipeline job.
PIPELINE_LOCK_ID = 1


async def try_advisory_lock(session: AsyncSession, lock_id: int) -> bool:
    """Try to acquire a PostgreSQL transaction-level advisory lock.

    Returns True if acquired, False if already held by another transaction.
    The lock auto-releases at COMMIT or ROLLBACK — no explicit release needed,
    and the lock is guaranteed to be freed even if the session connection is
    recycled by the pool between commits.
    """
    result = await session.execute(
        text("SELECT pg_try_advisory_xact_lock(:lock_id)"),
        {"lock_id": lock_id},
    )
    acquired: bool = result.scalar_one()
    logger.debug("try_advisory_lock: lock_id=%d acquired=%s", lock_id, acquired)
    return acquired
