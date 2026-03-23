from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

import httpx
from ru_name_generator import generate_russian_name

logger = logging.getLogger(__name__)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
ODESA_BBOX = "46.35,30.60,46.55,30.85"  # south,west,north,east
REQUEST_TIMEOUT = 60
RETRY_DELAYS = [5, 15, 45]


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _post_overpass(query: str) -> dict[str, Any]:
    """POST a query to the Overpass API with retry/backoff."""
    last_exc: Exception | None = None

    for attempt, delay in enumerate([0, *RETRY_DELAYS], start=1):
        if delay:
            logger.warning("Overpass retry %d/%d — waiting %ds", attempt, len(RETRY_DELAYS) + 1, delay)
            time.sleep(delay)

        try:
            resp = httpx.post(
                OVERPASS_URL,
                data={"data": query},
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()  # type: ignore[return-value]
        except httpx.HTTPError as exc:
            logger.error("Overpass request failed (attempt %d): %s", attempt, exc)
            last_exc = exc

    raise RuntimeError(f"Overpass API unreachable after {len(RETRY_DELAYS) + 1} attempts") from last_exc


# ---------------------------------------------------------------------------
# Street extraction
# ---------------------------------------------------------------------------


def _build_street_query() -> str:
    return f"""
[out:json][timeout:{REQUEST_TIMEOUT}];
(
  way[highway][name]({ODESA_BBOX});
  relation[type=street][name]({ODESA_BBOX});
);
out body;
>;
out skel qt;
"""


def _compute_centroid(coords: list[tuple[float, float]]) -> tuple[float, float]:
    """Return (lat, lng) mean of a list of coordinate pairs."""
    lats = [c[0] for c in coords]
    lngs = [c[1] for c in coords]
    return sum(lats) / len(lats), sum(lngs) / len(lngs)


def _finalize_streets(streets: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Compute centroids and fill missing Russian names via rule generator."""
    results: list[dict[str, Any]] = []

    for entry in streets.values():
        coords = entry.pop("coords")
        if not coords:
            logger.debug("Street has no resolvable node coords, skipping: %s", entry["name_uk"])
            continue

        lat, lng = _compute_centroid(coords)

        # Fill missing Russian name with rule-based generator
        if not entry["name_ru"]:
            generated = generate_russian_name(entry["name_uk"])
            if generated:
                entry["name_ru"] = generated
                entry["name_ru_source"] = "rules"
            else:
                entry["name_ru"] = entry["name_uk"]
                entry["name_ru_source"] = "fallback"

        results.append(
            {
                "name_uk": entry["name_uk"],
                "name_ru": entry["name_ru"],
                "name_ru_source": entry["name_ru_source"],
                "centroid_lat": round(lat, 6),
                "centroid_lng": round(lng, 6),
                "osm_ids": entry["osm_ids"],
            }
        )

    logger.info("Extracted %d streets", len(results))
    return results


# ---------------------------------------------------------------------------
# District extraction
# ---------------------------------------------------------------------------


def _build_district_query() -> str:
    return f"""
[out:json][timeout:{REQUEST_TIMEOUT}];
(
  relation[boundary=administrative]({ODESA_BBOX});
  relation[place=suburb]({ODESA_BBOX});
  relation[place=quarter]({ODESA_BBOX});
  relation[place=neighbourhood]({ODESA_BBOX});
  way[place=suburb]({ODESA_BBOX});
  way[place=quarter]({ODESA_BBOX});
  way[place=neighbourhood]({ODESA_BBOX});
);
out body;
>;
out skel qt;
"""


def _extract_polygon_from_way(way: dict[str, Any], nodes: dict[int, tuple[float, float]]) -> list[list[float]] | None:
    """Return [[lat, lng], ...] polygon from a way element."""
    way_nodes = way.get("nodes", [])
    coords = [list(nodes[n]) for n in way_nodes if n in nodes]
    return coords if len(coords) >= 3 else None  # noqa: PLR2004


def _extract_polygon_from_relation(
    rel: dict[str, Any],
    ways_index: dict[int, dict[str, Any]],
    nodes: dict[int, tuple[float, float]],
) -> list[list[float]] | None:
    """Build an approximate polygon from the outer members of a relation."""
    outer_coords: list[list[float]] = []

    for member in rel.get("members", []):
        if member.get("role") != "outer" or member.get("type") != "way":
            continue
        way = ways_index.get(member["ref"])
        if not way:
            continue
        for node_id in way.get("nodes", []):
            coord = nodes.get(node_id)
            if coord:
                outer_coords.append(list(coord))

    return outer_coords if len(outer_coords) >= 3 else None  # noqa: PLR2004


def extract_districts() -> list[dict[str, Any]]:
    """Query Overpass for district boundaries in Odesa."""
    logger.info("Fetching districts from Overpass API")
    data = _post_overpass(_build_district_query())

    nodes: dict[int, tuple[float, float]] = {}
    ways_index: dict[int, dict[str, Any]] = {}

    for element in data.get("elements", []):
        if element["type"] == "node":
            nodes[element["id"]] = (element["lat"], element["lon"])
        elif element["type"] == "way":
            ways_index[element["id"]] = element

    results: list[dict[str, Any]] = []

    for element in data.get("elements", []):
        tags = element.get("tags", {})
        name_uk = tags.get("name", "").strip()
        if not name_uk:
            continue

        name_ru = tags.get("name:ru", "").strip() or generate_russian_name(name_uk) or name_uk

        polygon: list[list[float]] | None = None
        if element["type"] == "way":
            polygon = _extract_polygon_from_way(element, nodes)
        elif element["type"] == "relation":
            polygon = _extract_polygon_from_relation(element, ways_index, nodes)

        if polygon is None:
            logger.debug("Could not extract polygon for district: %s", name_uk)
            continue

        results.append({"name_uk": name_uk, "name_ru": name_ru, "polygon": polygon})

    # Deduplicate by name_uk — keep first occurrence
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for r in results:
        if r["name_uk"] not in seen:
            seen.add(r["name_uk"])
            unique.append(r)

    logger.info("Extracted %d districts", len(unique))
    return unique


# ---------------------------------------------------------------------------
# Street rename extraction
# ---------------------------------------------------------------------------


def extract_street_renames(streets_raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Derive rename records from streets that have old_name tags."""
    renames: list[dict[str, Any]] = []

    for street in streets_raw:
        old_uk = street.get("old_name")
        if not old_uk:
            continue

        old_ru = street.get("old_name_ru") or generate_russian_name(old_uk)

        renames.append(
            {
                "old_name_uk": old_uk,
                "old_name_ru": old_ru,
                "new_name_uk": street["name_uk"],
                "new_name_ru": street.get("name_ru"),
                "year_renamed": None,
            }
        )

    logger.info("Extracted %d street renames", len(renames))
    return renames


# ---------------------------------------------------------------------------
# Top-level generate function
# ---------------------------------------------------------------------------


SUPPORTED_CITIES = {"odesa"}


def generate_all(city: str) -> dict[str, Any]:
    """Extract all OSM data for the given city and return structured payloads."""
    if city not in SUPPORTED_CITIES:
        msg = f"Unsupported city: {city}. Supported: {sorted(SUPPORTED_CITIES)}"
        raise ValueError(msg)

    generated_at = datetime.now(UTC).isoformat()

    # Streets also carry old_name data needed for renames — we keep internal
    # records separate from the final output format.
    raw_streets = _fetch_raw_streets()
    streets_output = _format_streets(raw_streets)
    renames_output = extract_street_renames(raw_streets)
    districts_output = extract_districts()

    return {
        "streets": {"city": city, "generated_at": generated_at, "streets": streets_output},
        "districts": {"city": city, "generated_at": generated_at, "districts": districts_output},
        "street_renames": {"city": city, "generated_at": generated_at, "renames": renames_output},
    }


def _fetch_raw_streets() -> list[dict[str, Any]]:
    """Return streets including internal old_name fields for rename extraction."""
    logger.info("Fetching streets (raw) from Overpass API")
    data = _post_overpass(_build_street_query())

    nodes: dict[int, tuple[float, float]] = {}
    for element in data.get("elements", []):
        if element["type"] == "node":
            nodes[element["id"]] = (element["lat"], element["lon"])

    streets: dict[str, dict[str, Any]] = {}

    for element in data.get("elements", []):
        if element["type"] != "way":
            continue
        tags = element.get("tags", {})
        name_uk = tags.get("name", "").strip()
        if not name_uk:
            continue

        if name_uk not in streets:
            name_ru_osm = tags.get("name:ru", "").strip() or None
            streets[name_uk] = {
                "name_uk": name_uk,
                "name_ru": name_ru_osm,
                "name_ru_source": "osm" if name_ru_osm else None,
                "old_name": tags.get("old_name", "").strip() or None,
                "old_name_ru": tags.get("old_name:ru", "").strip() or None,
                "coords": [],
                "osm_ids": [],
            }
        else:
            if not streets[name_uk]["name_ru"]:
                name_ru_osm = tags.get("name:ru", "").strip() or None
                if name_ru_osm:
                    streets[name_uk]["name_ru"] = name_ru_osm
                    streets[name_uk]["name_ru_source"] = "osm"

        streets[name_uk]["osm_ids"].append(element["id"])
        for node_id in element.get("nodes", []):
            coord = nodes.get(node_id)
            if coord:
                streets[name_uk]["coords"].append(coord)

    return list(streets.values())


def _format_streets(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert raw street dicts (with coords) into output format records."""
    results: list[dict[str, Any]] = []

    for entry in raw:
        coords = entry.get("coords", [])
        if not coords:
            continue

        lat, lng = _compute_centroid(coords)

        name_ru = entry["name_ru"]
        name_ru_source = entry["name_ru_source"]

        if not name_ru:
            generated = generate_russian_name(entry["name_uk"])
            if generated:
                name_ru = generated
                name_ru_source = "rules"
            else:
                name_ru = entry["name_uk"]
                name_ru_source = "fallback"

        results.append(
            {
                "name_uk": entry["name_uk"],
                "name_ru": name_ru,
                "name_ru_source": name_ru_source,
                "centroid_lat": round(lat, 6),
                "centroid_lng": round(lng, 6),
                "osm_ids": entry["osm_ids"],
            }
        )

    return results
