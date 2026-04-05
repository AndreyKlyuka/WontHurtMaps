from __future__ import annotations

import logging

from geoalchemy2.elements import WKTElement

from app.models.location import Location
from app.schemas.llm import ExtractedLocation
from app.services.geocoder import GeocodeResult

logger = logging.getLogger(__name__)

_GEO_TYPE_MAP: dict[str, str] = {
    "address": "point",
    "intersection": "point",
    "direction": "street",
    "district": "area",
    "landmark": "area",
}

_AUTO_RESOLVE_THRESHOLD = 0.7


class DataNormalizerService:
    """Pairs LLM extraction results with geocode results to create Location records.

    Responsibilities:
      - Calculate composite confidence: (extraction.confidence * 0.5) + (geocoder_confidence * 0.5)
      - Determine geo_type from extraction location_type
      - Set out_of_bounds flag from geocode result
      - Set resolved/resolved_by based on confidence threshold
      - Create Location ORM objects ready for persistence
    """

    def normalize(
        self,
        post_id: int,
        extractions: list[ExtractedLocation],
        geocode_results: dict[str, GeocodeResult | None],
    ) -> list[Location]:
        """Return list of Location ORM objects. Synchronous — no I/O.

        POLYLINE extractions produce two Location records (start + end point)
        when both endpoints geocode successfully; a single record when only
        one resolves.
        """
        locations: list[Location] = []
        skipped = 0

        for extraction in extractions:
            geocode_result = geocode_results.get(extraction.value)
            if geocode_result is None:
                skipped += 1
                continue

            geo_type = _GEO_TYPE_MAP[extraction.location_type]
            confidence = (extraction.confidence * 0.5) + (geocode_result.geocoder_confidence * 0.5)
            resolved, resolved_by = self._resolve(confidence)

            locations.append(
                self._make_location(
                    post_id, geocode_result, geo_type, extraction.value, confidence, resolved, resolved_by
                )
            )

            # POLYLINE: also persist the end point as a separate Location record
            if extraction.value_end is not None:
                geo_end = geocode_results.get(extraction.value_end)
                if geo_end is not None:
                    confidence_end = (extraction.confidence * 0.5) + (geo_end.geocoder_confidence * 0.5)
                    resolved_end, resolved_by_end = self._resolve(confidence_end)
                    locations.append(
                        self._make_location(
                            post_id,
                            geo_end,
                            geo_type,
                            extraction.value_end,
                            confidence_end,
                            resolved_end,
                            resolved_by_end,
                        )
                    )

        logger.debug(
            "data_normalizer: post_id=%d created=%d skipped=%d",
            post_id,
            len(locations),
            skipped,
        )
        return locations

    def _resolve(self, confidence: float) -> tuple[bool, str | None]:
        if confidence >= _AUTO_RESOLVE_THRESHOLD:
            return True, "auto"
        return False, None

    def _make_location(
        self,
        post_id: int,
        geocode_result: GeocodeResult,
        geo_type: str,
        address: str,
        confidence: float,
        resolved: bool,
        resolved_by: str | None,
    ) -> Location:
        return Location(
            post_id=post_id,
            geometry=WKTElement(
                f"POINT({geocode_result.lng} {geocode_result.lat})",
                srid=4326,
            ),
            geo_type=geo_type,
            address=address,
            street_name=None,
            confidence=confidence,
            out_of_bounds=geocode_result.out_of_bounds,
            resolved=resolved,
            resolved_by=resolved_by,
        )
