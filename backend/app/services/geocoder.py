from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx
from geoalchemy2.functions import ST_X, ST_Y, ST_Centroid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ExternalServiceCircuitOpen, GeocodingError
from app.models.city import City
from app.models.district import District
from app.models.street_rename import StreetRename
from app.repositories.district_repository import DistrictRepository
from app.repositories.geocode_cache_repository import GeocodeCacheRepository

logger = logging.getLogger(__name__)

_GOOGLE_CONFIDENCE: dict[str, float] = {
    "ROOFTOP": 0.95,
    "RANGE_INTERPOLATED": 0.8,
    "GEOMETRIC_CENTER": 0.6,
    "APPROXIMATE": 0.4,
}
_DEFAULT_CONFIDENCE = 0.3
_GEOCODE_API_URL = "https://maps.googleapis.com/maps/api/geocode/json"
_CITY_CONTEXT = "Одеса, Україна"


@dataclass
class GeocodeResult:
    lat: float
    lng: float
    result_type: str  # "rooftop", "range_interpolated", "geometric_center", "approximate"
    geocoder_confidence: float  # derived from result_type
    out_of_bounds: bool
    from_cache: bool


class GeocoderService:
    """Geocodes extracted addresses to lat/lng coordinates.

    Resolution chain per address:
      1. Geocode cache lookup (GeocodeCacheRepository)
      2. Street rename mapping (old_name -> new_name substitution)
      3. Google Maps Geocoding API call
      4. District fallback (for location_type="district" only)
      5. Bounding box validation

    Features:
      - Cache hit -> increment hit_count, return immediately
      - Cache miss -> call Google Maps API, save to cache on success
      - Out-of-bounds: flag with out_of_bounds=True AND apply x 0.3 confidence penalty
      - Circuit breaker: 3 consecutive Google Maps failures -> ExternalServiceCircuitOpen
      - Circuit breaker is per-cycle only — new instance per cycle
    """

    def __init__(
        self,
        session: AsyncSession,
        city: City,
        street_renames: list[StreetRename],
    ) -> None:
        self._session = session
        self._city = city
        self._cache_repo = GeocodeCacheRepository(session)
        self._district_repo = DistrictRepository(session)
        self._consecutive_failures: int = 0

        # Pre-build rename lookup dicts — only active renames
        self._rename_uk: dict[str, str] = {}
        self._rename_ru: dict[str, str] = {}
        for rename in street_renames:
            if rename.status != "active":
                continue
            self._rename_uk[rename.old_name_uk.lower()] = rename.new_name_uk
            if rename.old_name_ru is not None and rename.new_name_ru is not None:
                self._rename_ru[rename.old_name_ru.lower()] = rename.new_name_ru

    async def geocode(self, address: str, location_type: str) -> GeocodeResult | None:
        """Resolve address to coordinates.

        Returns GeocodeResult or None if all fallbacks fail.
        Raises ExternalServiceCircuitOpen after consecutive failures threshold.
        """
        # 1. Cache lookup
        cached = await self._cache_repo.lookup(self._city.id, address)
        if cached is not None:
            logger.debug(
                "geocoder cache hit: address=%r result_type=%s",
                address,
                cached.result_type,
            )
            confidence = _GOOGLE_CONFIDENCE.get(cached.result_type.upper(), _DEFAULT_CONFIDENCE)
            out_of_bounds = not self._in_bounds(cached.result_lat, cached.result_lng)
            if out_of_bounds:
                confidence *= 0.3
            return GeocodeResult(
                lat=cached.result_lat,
                lng=cached.result_lng,
                result_type=cached.result_type,
                geocoder_confidence=confidence,
                out_of_bounds=out_of_bounds,
                from_cache=True,
            )

        # 2. Apply street rename substitution
        resolved_address = self._apply_renames(address)

        # 3. Google Maps API call
        api_result = await self._call_google_maps(resolved_address)

        # 4. District fallback
        if api_result is None and location_type == "district":
            return await self._district_fallback(address)

        if api_result is None:
            return None

        lat, lng, raw_location_type = api_result
        confidence = _GOOGLE_CONFIDENCE.get(raw_location_type.upper(), _DEFAULT_CONFIDENCE)

        # 5. Bounding box validation
        out_of_bounds = not self._in_bounds(lat, lng)
        if out_of_bounds:
            confidence *= 0.3

        # Save to cache (use normalised result_type string)
        result_type = raw_location_type.lower()
        await self._cache_repo.save(self._city.id, address, lat, lng, result_type)

        logger.debug(
            "geocoder api success: address=%r lat=%f lng=%f result_type=%s confidence=%f out_of_bounds=%s",
            address,
            lat,
            lng,
            result_type,
            confidence,
            out_of_bounds,
        )
        return GeocodeResult(
            lat=lat,
            lng=lng,
            result_type=result_type,
            geocoder_confidence=confidence,
            out_of_bounds=out_of_bounds,
            from_cache=False,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _apply_renames(self, address: str) -> str:
        """Substitute any known old street name substrings with their new names."""
        address_lower = address.lower()
        for old_lower, new_name in self._rename_uk.items():
            if old_lower in address_lower:
                # Replace preserving original case boundaries
                idx = address_lower.index(old_lower)
                address = address[:idx] + new_name + address[idx + len(old_lower) :]
                address_lower = address.lower()
        for old_lower, new_name in self._rename_ru.items():
            if old_lower in address_lower:
                idx = address_lower.index(old_lower)
                address = address[:idx] + new_name + address[idx + len(old_lower) :]
                address_lower = address.lower()
        return address

    async def _call_google_maps(self, address: str) -> tuple[float, float, str] | None:
        """Call Google Maps Geocoding API.

        Returns (lat, lng, location_type) on success, None on ZERO_RESULTS.
        Raises ExternalServiceCircuitOpen when consecutive failure threshold exceeded.
        Raises GeocodingError on non-recoverable API error (after incrementing counter).
        """
        if self._consecutive_failures >= settings.geocoding_max_consecutive_failures:
            raise ExternalServiceCircuitOpen("Google Maps")

        params = {
            "address": f"{address}, {_CITY_CONTEXT}",
            "key": settings.google_maps_api_key,
            "language": "uk",
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(_GEOCODE_API_URL, params=params)
                response.raise_for_status()
                data = response.json()
        except (httpx.TimeoutException, httpx.HTTPError) as exc:
            self._consecutive_failures += 1
            logger.warning(
                "geocoder http error: address=%r failures=%d error=%s",
                address,
                self._consecutive_failures,
                exc,
            )
            if self._consecutive_failures >= settings.geocoding_max_consecutive_failures:
                logger.info(
                    "geocoder circuit open: consecutive_failures=%d",
                    self._consecutive_failures,
                )
                raise ExternalServiceCircuitOpen("Google Maps") from exc
            raise GeocodingError(address) from exc

        status = data.get("status", "")

        if status == "ZERO_RESULTS":
            # Not a failure — address simply not found
            return None

        if status != "OK":
            self._consecutive_failures += 1
            logger.warning(
                "geocoder api error: address=%r status=%s failures=%d",
                address,
                status,
                self._consecutive_failures,
            )
            if self._consecutive_failures >= settings.geocoding_max_consecutive_failures:
                logger.info(
                    "geocoder circuit open: consecutive_failures=%d",
                    self._consecutive_failures,
                )
                raise ExternalServiceCircuitOpen("Google Maps")
            raise GeocodingError(address)

        # Success — reset failure counter
        self._consecutive_failures = 0

        first = data["results"][0]
        location = first["geometry"]["location"]
        location_type = first["geometry"]["location_type"]
        return location["lat"], location["lng"], location_type

    async def _district_fallback(self, address: str) -> GeocodeResult | None:
        """Return centroid of a district polygon when API yields no result."""
        district = await self._district_repo.find_by_name(self._city.id, address)
        if district is None:
            return None

        stmt = select(
            ST_X(ST_Centroid(District.polygon)),
            ST_Y(ST_Centroid(District.polygon)),
        ).where(District.id == district.id)
        row = (await self._session.execute(stmt)).one_or_none()
        if row is None:
            return None

        centroid_lng, centroid_lat = float(row[0]), float(row[1])
        logger.debug(
            "geocoder district fallback: address=%r district_id=%d lat=%f lng=%f",
            address,
            district.id,
            centroid_lat,
            centroid_lng,
        )
        return GeocodeResult(
            lat=centroid_lat,
            lng=centroid_lng,
            result_type="geometric_center",
            geocoder_confidence=0.5,
            out_of_bounds=False,
            from_cache=False,
        )

    def _in_bounds(self, lat: float, lng: float) -> bool:
        """Return True if the coordinate falls within the city bounding box."""
        return (
            self._city.bbox_south <= lat <= self._city.bbox_north
            and self._city.bbox_west <= lng <= self._city.bbox_east
        )
