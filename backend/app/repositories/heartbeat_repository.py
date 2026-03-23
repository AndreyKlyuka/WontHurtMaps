from __future__ import annotations

import logging

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import WorkerHeartbeat

logger = logging.getLogger(__name__)


class HeartbeatRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_heartbeat(
        self,
        status: str,
        current_job: str | None = None,
        posts_processed: int = 0,
    ) -> None:
        """Insert or update the single heartbeat row (id=1).

        Uses INSERT ... ON CONFLICT (id) DO UPDATE.
        """
        stmt = (
            insert(WorkerHeartbeat)
            .values(
                id=1,
                status=status,
                current_job=current_job,
                posts_processed=posts_processed,
            )
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "heartbeat_at": func.now(),
                    "status": status,
                    "current_job": current_job,
                    "posts_processed": posts_processed,
                },
            )
        )
        await self._session.execute(stmt)
        await self._session.flush()
        logger.debug("upsert_heartbeat: status=%s job=%s", status, current_job)
