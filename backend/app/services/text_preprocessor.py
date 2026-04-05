from __future__ import annotations

import logging
import re
import unicodedata

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Compiled regex patterns — built once at import time.
# ---------------------------------------------------------------------------

# Supplementary Multilingual Plane characters (U+10000–U+10FFFF).
# Covers virtually all emoji that live outside the BMP.
_RE_EMOJI_SMP = re.compile(
    "[\U00010000-\U0010ffff]",
    flags=re.UNICODE,
)

# Emoji and miscellaneous symbol blocks in the BMP:
#   U+2600–U+27BF  — Miscellaneous Symbols, Dingbats, etc.
#   U+2B00–U+2BFF  — Miscellaneous Symbols and Arrows
#   U+1F300–U+1FAFF — main emoji block (already in SMP range, kept for clarity)
# We also strip variation selectors (U+FE00–U+FE0F) used to trigger emoji presentation.
_RE_EMOJI_BMP = re.compile(
    "[\u2600-\u27bf\u2b00-\u2bff\ufe00-\ufe0f]",
    flags=re.UNICODE,
)

# Telegram markdown: bold (**), italic (__), strikethrough (~~), spoiler (||).
# Order matters — longer delimiters first so ** is not partially eaten by a
# hypothetical single-star rule.
_RE_MD_DELIMITERS = re.compile(r"\*\*|__|~~|\|\|")

# Markdown hyperlinks: [visible text](url) → keep visible text only.
_RE_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")

# One or more whitespace characters (space, tab, newline, carriage return, etc.).
_RE_WHITESPACE = re.compile(r"\s+")

# ---------------------------------------------------------------------------
# Confusable character map
# ---------------------------------------------------------------------------
# These substitutions are intentionally narrow: only characters that are
# visually identical or near-identical to their replacements and that appear
# regularly in mixed Russian/Ukrainian Telegram posts.
_CONFUSABLE_MAP: dict[str, str] = {
    "ё": "е",  # Russian yo → ye (Ukrainian posts drop this distinction)
    "Ё": "Е",
}


class TextPreprocessorService:
    """Cleans raw Telegram post text for LLM extraction.

    Steps:
      1. Remove emoji and special Unicode symbols
      2. Remove Telegram formatting artifacts (**, __, ~~, ||, markdown links)
      3. Unicode normalization (NFC): canonical composition
      4. Confusable character substitution: ё→е, Ё→Е
      5. Collapse multiple whitespace/newlines into single space
      6. Strip leading/trailing whitespace

    NOTE: Slang replacement is intentionally omitted — the LLM handles
    colloquial names via prompt context and few-shot examples.
    """

    def preprocess(self, raw_text: str) -> str:
        """Return a cleaned copy of *raw_text*.

        Synchronous — no I/O, no external dependencies.
        """
        text = raw_text

        # Step 1 — remove emoji.
        text = _RE_EMOJI_SMP.sub("", text)
        text = _RE_EMOJI_BMP.sub("", text)

        # Step 2 — strip Telegram markdown formatting.
        text = _RE_MD_LINK.sub(r"\1", text)  # [label](url) → label
        text = _RE_MD_DELIMITERS.sub("", text)

        # Step 3 — Unicode NFC normalization.
        text = unicodedata.normalize("NFC", text)

        # Step 4 — confusable substitutions.
        for source, target in _CONFUSABLE_MAP.items():
            text = text.replace(source, target)

        # Step 5+6 — collapse whitespace and strip.
        text = _RE_WHITESPACE.sub(" ", text).strip()

        logger.debug(
            "preprocessed post",
            extra={"raw_len": len(raw_text), "cleaned_len": len(text)},
        )

        return text
