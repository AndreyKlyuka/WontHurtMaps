from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ExtractedLocation(BaseModel):
    """Single location extracted from post text by LLM."""

    location_type: Literal["address", "intersection", "direction", "district", "landmark"]
    map_hint: Literal["MARKER", "CIRCLE", "POLYLINE"]
    value: str  # normalized, geocodable (start point for POLYLINE)
    value_end: str | None = None  # end point for POLYLINE only
    confidence: float = Field(ge=0.0, le=1.0)


class LLMExtractionResult(BaseModel):
    """Validated response from LLM extraction."""

    locations: list[ExtractedLocation] = Field(default_factory=list)
