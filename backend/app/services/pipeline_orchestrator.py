from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ExternalServiceCircuitOpen
from app.models.city import City
from app.models.location import Location
from app.models.post import Post
from app.repositories.district_repository import DistrictRepository
from app.repositories.location_repository import LocationRepository
from app.repositories.post_repository import PostRepository
from app.repositories.street_rename_repository import StreetRenameRepository
from app.repositories.unrecognized_token_repository import UnrecognizedTokenRepository
from app.services.data_normalizer import DataNormalizerService
from app.services.geocoder import GeocodeResult, GeocoderService
from app.services.llm_extractor import LLMExtractorService
from app.services.text_preprocessor import TextPreprocessorService

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    posts_processed: int = field(default=0)
    posts_failed: int = field(default=0)
    locations_created: int = field(default=0)
    cache_hits: int = field(default=0)
    unrecognized_count: int = field(default=0)
    skipped_circuit_open: bool = field(default=False)


class PipelineOrchestrator:
    """Coordinates the full text processing pipeline.

    Flow per cycle:
      1. Load cycle-level data: city, districts, street renames, few-shot examples
      2. Fetch pending posts (limit = settings.llm_queue_max)
      3. Also fetch retryable failed posts (retry_count < 3)
      4. For each post (with savepoint per post):
         a. Preprocess -> set cleaned_text, post.status = "preprocessed"
         b. LLM extract -> get location candidates
         c. Geocode each candidate
         d. Normalize -> create Location records
         e. Save locations (bulk_save_locations)
         f. Log unrecognized tokens (extracted but geocode_result is None)
         g. Update post status (resolved/unresolved based on whether locations were created)
      5. On per-post exception: rollback savepoint, mark post failed
      6. On ExternalServiceCircuitOpen: stop processing, remaining stay pending
      7. commit session after all posts processed
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def run(self) -> PipelineResult:
        """Execute full processing cycle. Returns summary stats."""
        # --- 1. Load cycle-level data ---

        city_result = await self._session.execute(select(City).limit(1))
        city = city_result.scalar_one()

        district_repo = DistrictRepository(self._session)
        all_districts = await district_repo.get_all(city.id)
        district_names = [d.name for d in all_districts]

        rename_repo = StreetRenameRepository(self._session)
        street_renames = await rename_repo.get_active_renames(city.id)

        few_shot_examples = await self._load_few_shot_examples()

        # --- 2 & 3. Fetch posts ---

        post_repo = PostRepository(self._session)
        posts = await post_repo.get_pending_posts(limit=settings.llm_queue_max)
        retryable = await post_repo.get_retryable_posts(limit=100)
        all_posts = posts + retryable

        logger.info(
            "Processing pipeline starting",
            extra={
                "pending": len(posts),
                "retryable": len(retryable),
                "total": len(all_posts),
            },
        )

        # --- Build per-cycle service instances ---

        preprocessor = TextPreprocessorService()
        llm = LLMExtractorService(city_name=city.name, districts=district_names)
        llm.set_few_shot_examples(few_shot_examples)
        geocoder = GeocoderService(self._session, city, street_renames)
        normalizer = DataNormalizerService()
        location_repo = LocationRepository(self._session)
        token_repo = UnrecognizedTokenRepository(self._session)

        result = PipelineResult()

        # --- 4. Process each post ---

        for post in all_posts:
            # Pre-read id before any savepoints — after savepoint rollback SQLAlchemy
            # expires ALL attributes (including PKs), so we need id as a local variable
            # for the error-handling path that runs after the savepoint context exits.
            post_id = post.id
            circuit_open = False
            post_exc: Exception | None = None

            try:
                async with self._session.begin_nested():
                    # a. Preprocess
                    cleaned = preprocessor.preprocess(post.raw_text)
                    post.cleaned_text = cleaned
                    post.status = "preprocessed"

                    # b. LLM extract
                    extraction_result = await llm.extract(cleaned)

                    if not extraction_result.locations:
                        post.status = "unresolved"
                        result.posts_processed += 1
                        continue

                    # c. Geocode each candidate (POLYLINE geocodes both endpoints)
                    geocode_results: dict[str, GeocodeResult | None] = {}
                    for extracted in extraction_result.locations:
                        geo = await geocoder.geocode(extracted.value, extracted.location_type)
                        geocode_results[extracted.value] = geo
                        if geo is not None and geo.from_cache:
                            result.cache_hits += 1
                        if extracted.value_end is not None:
                            geo_end = await geocoder.geocode(extracted.value_end, extracted.location_type)
                            geocode_results[extracted.value_end] = geo_end
                            if geo_end is not None and geo_end.from_cache:
                                result.cache_hits += 1

                    # d. Normalize
                    locations = normalizer.normalize(post.id, extraction_result.locations, geocode_results)

                    # e. Save locations
                    if locations:
                        count = await location_repo.bulk_save_locations(locations)
                        result.locations_created += count
                        post.status = "resolved"
                    else:
                        post.status = "unresolved"

                    # f. Log unrecognized tokens (check both value and value_end)
                    for extracted in extraction_result.locations:
                        if geocode_results.get(extracted.value) is None:
                            await token_repo.upsert(city.id, extracted.value, post.id)
                            result.unrecognized_count += 1
                        if extracted.value_end is not None and geocode_results.get(extracted.value_end) is None:
                            await token_repo.upsert(city.id, extracted.value_end, post.id)
                            result.unrecognized_count += 1

                    # g. Reset retry state on retried posts that succeed
                    if post.retry_count > 0:
                        post.retry_count = 0
                        post.error_message = None

                # Savepoint committed — count success
                result.posts_processed += 1

            except ExternalServiceCircuitOpen:
                circuit_open = True

            except Exception as exc:
                post_exc = exc

            if circuit_open:
                result.skipped_circuit_open = True
                logger.warning("Circuit breaker open — stopping pipeline cycle")
                break

            if post_exc is not None:
                # Use direct UPDATE to avoid reading expired ORM attributes after savepoint rollback.
                # update_post_status increments retry_count via SQL expression (no lazy load needed).
                await post_repo.update_post_status(post_id, "failed", error_message=str(post_exc)[:500])
                result.posts_failed += 1
                logger.error(
                    "Post processing failed",
                    extra={"post_id": post_id, "error": str(post_exc)},
                )

        await self._session.commit()

        logger.info(
            "Processing pipeline complete",
            extra={
                "posts_processed": result.posts_processed,
                "posts_failed": result.posts_failed,
                "locations_created": result.locations_created,
                "cache_hits": result.cache_hits,
                "unrecognized_count": result.unrecognized_count,
                "skipped_circuit_open": result.skipped_circuit_open,
            },
        )

        return result

    async def _load_few_shot_examples(self) -> list[dict]:
        """Query locations table for 3 random high-confidence verified examples.

        Falls back to empty list (LLMExtractorService uses bootstrap examples).
        """
        stmt = (
            select(Location.address, Location.geo_type, Post.raw_text)
            .join(Post, Location.post_id == Post.id)
            .where(
                Location.confidence >= 0.95,
                Location.resolved.is_(True),
                Location.resolved_by.is_not(None),
            )
            .order_by(func.random())
            .limit(3)
        )
        result = await self._session.execute(stmt)
        rows = result.mappings().all()
        return [
            {
                "text": row["raw_text"],
                "locations": [
                    {
                        "location_type": "address",
                        "map_hint": "MARKER",
                        "value": row["address"],
                        "value_end": None,
                        "confidence": 0.95,
                    }
                ],
            }
            for row in rows
        ]
