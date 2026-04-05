from __future__ import annotations

import asyncio
import json
import logging
import random
import time

import httpx

from app.core.config import settings
from app.core.exceptions import ExternalServiceCircuitOpen, LLMExtractionError
from app.schemas.llm import LLMExtractionResult

logger = logging.getLogger(__name__)

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"

_BOOTSTRAP_EXAMPLES: list[dict] = [
    {
        "text": "Обережно! ДТП на вул. Дерибасівська, 15. Перекрито рух.",
        "locations": [
            {
                "location_type": "address",
                "map_hint": "MARKER",
                "value": "Дерибасівська вулиця, 15",
                "value_end": None,
                "confidence": 0.95,
            }
        ],
    },
    {
        "text": "Стріляли на розі Пушкінської та Рішельєвської, є поранені",
        "locations": [
            {
                "location_type": "intersection",
                "map_hint": "MARKER",
                "value": "Пушкінська вулиця та Рішельєвська вулиця",
                "value_end": None,
                "confidence": 0.75,
            }
        ],
    },
    {
        "text": "Підозріла машина їде з Костанді на Королева у бік Пересипу",
        "locations": [
            {
                "location_type": "direction",
                "map_hint": "POLYLINE",
                "value": "вулиця Костанді",
                "value_end": "вулиця Королева",
                "confidence": 0.65,
            }
        ],
    },
    {
        "text": "Бійка біля Привозу, викликали поліцію",
        "locations": [
            {
                "location_type": "landmark",
                "map_hint": "CIRCLE",
                "value": "Привоз ринок",
                "value_end": None,
                "confidence": 0.6,
            }
        ],
    },
    {
        "text": "На Фонтані сильні вибухи, не виходьте з дому",
        "locations": [
            {
                "location_type": "direction",
                "map_hint": "CIRCLE",
                "value": "Фонтан",
                "value_end": None,
                "confidence": 0.45,
            }
        ],
    },
    {
        "text": "Черноморка будьте пильними сьогодні",
        "locations": [
            {
                "location_type": "district",
                "map_hint": "CIRCLE",
                "value": "Чорноморка",
                "value_end": None,
                "confidence": 0.3,
            }
        ],
    },
]

# Static per city — sent as system_instruction, separate from post content.
_SYSTEM_PROMPT_TEMPLATE = """\
You are a location extractor for the city of {city_name}, Ukraine.
Given a Telegram post about dangerous situations, extract all mentioned locations.

Known districts: {districts_csv}

## Location Types

- address: street + building number
- intersection: two crossing streets
- direction: street without a building number
- district: named neighborhood or administrative district
- landmark: named place (market, station, park, hospital, shopping center)

## map_hint

- MARKER → address or intersection (exact point)
- CIRCLE → direction, district, landmark, or any vague area
- POLYLINE → explicit movement described (від X до Y / з X на Y)

## Value Normalization

Normalize extracted text so it can be passed directly to a geocoder:
- Expand abbreviations: вул. → вулиця, просп./пр-т → проспект, бульв. → бульвар, пл. → площа, провул. → провулок
- Remove colloquial prefixes: "на Дерибасівській" → "Дерибасівська вулиця"
- For POLYLINE: value = start point (normalized), value_end = end point (normalized)
- Keep Ukrainian — do NOT transliterate or translate

## Confidence

- 0.9+: street + building number explicitly stated
- 0.75: two named streets at an intersection
- 0.6: named landmark (market, station, etc.)
- 0.45: street without a number, or vague direction
- 0.3: district or neighborhood name only

## Do NOT extract

- City name alone ("Одеса", "Одессе") or country ("Україна")
- Time references ("вчора", "зараз", "о 3-й ночі")
- Emotional phrases with no specific place ("будьте обережні", "небезпечно")\
"""

# Per-post — includes few-shot examples and the post to process.
_USER_TEMPLATE = """\
Examples:
{few_shot_block}

Return ONLY valid JSON:
{{"locations": [{{"location_type": "...", "map_hint": "...", "value": "...", "value_end": null, "confidence": 0.0}}]}}
If no locations found: {{"locations": []}}

Post: {cleaned_text}\
"""

_JSON_RETRY_SUFFIX = "\n\nIMPORTANT: Return ONLY valid JSON, no other text."


class LLMExtractorService:
    """Extracts structured location data from post text using Google Gemini API.

    Features:
      - system_instruction: static city context (name, districts, normalization rules)
      - User message: dynamic few-shot examples (3 random) + post text
      - 6 bootstrap examples covering all location types and edge cases
      - Structured JSON output -> Pydantic validation
      - Rate limiter: 15 RPM token bucket
      - Retry once on malformed JSON
      - Circuit breaker: 3 consecutive failures -> ExternalServiceCircuitOpen
      - Circuit breaker is per-cycle only — new instance per cycle, state not persisted
    """

    _MAX_TOKENS: float = 15.0
    _REFILL_RATE: float = 0.25  # tokens per second (15 per 60 s)
    _FEW_SHOT_COUNT: int = 3

    def __init__(self, city_name: str, districts: list[str]) -> None:
        """Initialize with city context for prompt construction.

        city_name: e.g. "Одеса"
        districts: list of district names for prompt context
        """
        self._city_name = city_name
        self._districts = districts
        self._few_shot_examples: list[dict] = []
        self._consecutive_failures: int = 0

        # Token bucket state
        self._tokens: float = self._MAX_TOKENS
        self._last_refill: float = time.monotonic()

        # System prompt is static per city — built once at init
        self._system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
            city_name=city_name,
            districts_csv=", ".join(districts),
        )

    def set_few_shot_examples(self, examples: list[dict]) -> None:
        """Set dynamic few-shot examples for this cycle.

        Each example dict: {"text": "...", "locations": [...]}
        Called once before extract() calls begin.
        """
        self._few_shot_examples = examples

    async def extract(self, cleaned_text: str) -> LLMExtractionResult:
        """Call Gemini API, validate response, return extraction result.

        Raises LLMExtractionError on permanent failure for this post.
        Raises ExternalServiceCircuitOpen after consecutive_failures >= threshold.
        On success, resets consecutive_failures to 0.
        """
        user_message = self._build_user_message(cleaned_text)
        await self._acquire_token()

        try:
            result = await self._call_with_retry(user_message)
        except LLMExtractionError:
            self._record_failure()
            raise
        except Exception as exc:
            self._record_failure()
            raise LLMExtractionError(detail=str(exc)) from exc

        self._consecutive_failures = 0
        logger.debug(
            "LLM extraction succeeded",
            extra={"location_count": len(result.locations)},
        )
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_few_shot_block(self) -> str:
        pool = self._few_shot_examples
        if len(pool) < self._FEW_SHOT_COUNT:
            pool = _BOOTSTRAP_EXAMPLES

        chosen = random.sample(pool, min(self._FEW_SHOT_COUNT, len(pool)))
        lines: list[str] = []
        for ex in chosen:
            locations_json = json.dumps(ex["locations"], ensure_ascii=False)
            lines.append(f'Post: "{ex["text"]}"\nOutput: {{"locations": {locations_json}}}')
        return "\n\n".join(lines)

    def _build_user_message(self, cleaned_text: str, *, retry_suffix: bool = False) -> str:
        few_shot_block = self._build_few_shot_block()
        message = _USER_TEMPLATE.format(
            few_shot_block=few_shot_block,
            cleaned_text=cleaned_text,
        )
        if retry_suffix:
            message += _JSON_RETRY_SUFFIX
        return message

    async def _acquire_token(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(
            self._MAX_TOKENS,
            self._tokens + elapsed * self._REFILL_RATE,
        )
        self._last_refill = now

        if self._tokens < 1.0:
            wait = (1.0 - self._tokens) / self._REFILL_RATE
            logger.debug("Rate limit: sleeping %.2fs for token refill", wait)
            await asyncio.sleep(wait)
            self._tokens = 0.0
        else:
            self._tokens -= 1.0

    async def _call_with_retry(self, user_message: str) -> LLMExtractionResult:
        """Issue the API call; retry once with JSON suffix on parse failure."""
        raw_text = await self._post_to_gemini(user_message)
        parsed = self._try_parse_json(raw_text)

        if parsed is None:
            logger.warning("JSON parse failed on first attempt, retrying")
            retry_message = user_message + _JSON_RETRY_SUFFIX
            raw_text = await self._post_to_gemini(retry_message)
            parsed = self._try_parse_json(raw_text)
            if parsed is None:
                raise LLMExtractionError(detail="JSON parse failed after retry")

        try:
            return LLMExtractionResult.model_validate(parsed)
        except Exception as exc:
            raise LLMExtractionError(detail="response schema invalid") from exc

    async def _post_to_gemini(self, user_message: str) -> str:
        """POST to Gemini using system_instruction + user message separation."""
        url = _GEMINI_URL.format(api_key=settings.gemini_api_key)
        body = {
            "system_instruction": {"parts": [{"text": self._system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_message}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2048},
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, json=body)
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise LLMExtractionError(detail="request timed out") from exc
        except httpx.HTTPStatusError as exc:
            raise LLMExtractionError(detail=f"HTTP {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise LLMExtractionError(detail=f"network error: {exc}") from exc

        return self._extract_text_from_response(response.json())

    def _extract_text_from_response(self, data: dict[str, object]) -> str:
        try:
            candidates = data["candidates"]
            assert isinstance(candidates, list)
            text = candidates[0]["content"]["parts"][0]["text"]  # type: ignore[index]
            assert isinstance(text, str)
            return text
        except (KeyError, IndexError, TypeError, AssertionError) as exc:
            raise LLMExtractionError(detail="unexpected Gemini response shape") from exc

    def _try_parse_json(self, text: str) -> dict[str, object] | None:
        text = text.strip()
        # Strip markdown code fences if the model wraps output in them.
        # Handle both complete fences (```json ... ```) and truncated ones (no closing ```).
        if text.startswith("```"):
            lines = text.splitlines()
            # Skip the opening fence line; drop closing ``` line if present
            inner_lines = lines[1:]
            if inner_lines and inner_lines[-1].startswith("```"):
                inner_lines = inner_lines[:-1]
            text = "\n".join(inner_lines).strip()
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None

    def _record_failure(self) -> None:
        self._consecutive_failures += 1
        logger.warning(
            "LLM extraction failure recorded",
            extra={
                "attempt": self._consecutive_failures,
                "error": "LLMExtractionError",
            },
        )
        if self._consecutive_failures >= settings.llm_max_consecutive_failures:
            logger.info(
                "Circuit breaker opened for Gemini after %d consecutive failures",
                self._consecutive_failures,
            )
            raise ExternalServiceCircuitOpen("Gemini")
