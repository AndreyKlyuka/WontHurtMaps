from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Maps Ukrainian street type tokens to Russian equivalents.
# Token matching is case-insensitive and word-boundary aware.
_STREET_TYPE_MAP: dict[str, str] = {
    "вулиця": "улица",
    "провулок": "переулок",
    "площа": "площадь",
    "бульвар": "бульвар",
    "проспект": "проспект",
    "набережна": "набережная",
    "шосе": "шоссе",
    "узвіз": "спуск",
    "тупик": "тупик",
}

# Compiled patterns: (uk_pattern, ru_replacement)
_COMPILED: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b" + re.escape(uk) + r"\b", re.IGNORECASE), ru) for uk, ru in _STREET_TYPE_MAP.items()
]


def generate_russian_name(ukrainian_name: str) -> str | None:
    """Produce a Russian street name from a Ukrainian one using rule-based substitution.

    Returns None when no street-type keyword is found — the caller should treat
    the absence of a translation as unknown rather than silently using the
    Ukrainian string as-is.
    """
    if not ukrainian_name or not ukrainian_name.strip():
        return None

    result = ukrainian_name.strip()
    matched = False

    for pattern, ru_type in _COMPILED:
        new_result, n = pattern.subn(ru_type, result)
        if n:
            result = new_result
            matched = True

    if not matched:
        logger.debug("No street-type keyword found for transliteration: %s", ukrainian_name)
        return None

    return result
