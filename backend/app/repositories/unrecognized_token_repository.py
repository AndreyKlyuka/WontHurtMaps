from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_MAX_SAMPLE_IDS = 5


class UnrecognizedTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, city_id: int, token: str, post_id: int) -> None:
        """INSERT ... ON CONFLICT (city_id, token) DO UPDATE:

        - increment occurrence_count
        - update last_seen_at
        - append post_id to sample_post_ids (max 5 elements)

        Array trimming uses PostgreSQL slice notation (1-based inclusive) to keep
        only the most recent _MAX_SAMPLE_IDS post IDs without unbounded growth.
        """
        now = datetime.now(UTC)

        stmt = text(
            """
            INSERT INTO unrecognized_tokens
                (city_id, token, occurrence_count, sample_post_ids, first_seen_at, last_seen_at)
            VALUES
                (:city_id, :token, 1, ARRAY[:post_id]::bigint[], :now, :now)
            ON CONFLICT ON CONSTRAINT uq_unrecognized_tokens_city_token DO UPDATE
            SET
                occurrence_count = unrecognized_tokens.occurrence_count + 1,
                last_seen_at     = :now,
                sample_post_ids  = CASE
                    WHEN unrecognized_tokens.sample_post_ids IS NULL
                        THEN ARRAY[:post_id]::bigint[]
                    WHEN array_length(unrecognized_tokens.sample_post_ids, 1) >= :max_ids
                        THEN (unrecognized_tokens.sample_post_ids || ARRAY[:post_id]::bigint[])
                             [array_length(unrecognized_tokens.sample_post_ids, 1) - :max_ids + 2
                              : array_length(unrecognized_tokens.sample_post_ids, 1) + 1]
                    ELSE unrecognized_tokens.sample_post_ids || ARRAY[:post_id]::bigint[]
                END
            """
        )

        await self._session.execute(
            stmt,
            {
                "city_id": city_id,
                "token": token,
                "post_id": post_id,
                "now": now,
                "max_ids": _MAX_SAMPLE_IDS,
            },
        )
        await self._session.flush()
        logger.debug(
            "unrecognized_token upsert: city_id=%d token=%r post_id=%d",
            city_id,
            token,
            post_id,
        )
