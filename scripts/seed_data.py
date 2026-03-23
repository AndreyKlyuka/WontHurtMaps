from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Allow importing sibling scripts and backend package when run standalone.
_SCRIPTS_DIR = Path(__file__).parent
_BACKEND_DIR = _SCRIPTS_DIR.parent / "backend"
sys.path.insert(0, str(_SCRIPTS_DIR))
sys.path.insert(0, str(_BACKEND_DIR))

import osm_extractor  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = _SCRIPTS_DIR.parent / "data" / "seed"

CITY_DEFAULTS: dict[str, dict[str, object]] = {
    "odesa": {
        "name": "Одеса",
        "name_ru": "Одесса",
        "bbox_north": 46.55,
        "bbox_south": 46.35,
        "bbox_east": 30.85,
        "bbox_west": 30.60,
        "default_zoom": 13,
    },
}


# ---------------------------------------------------------------------------
# generate command
# ---------------------------------------------------------------------------


def cmd_generate(city: str) -> None:
    """Extract OSM data and write JSON seed files to data/seed/."""
    logger.info("Generating seed data for city: %s", city)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    payloads = osm_extractor.generate_all(city)

    _write_json(DATA_DIR / "streets.json", payloads["streets"])
    _write_json(DATA_DIR / "districts.json", payloads["districts"])
    _write_json(DATA_DIR / "street_renames.json", payloads["street_renames"])

    logger.info(
        "Done. streets=%d  districts=%d  renames=%d",
        len(payloads["streets"]["streets"]),
        len(payloads["districts"]["districts"]),
        len(payloads["street_renames"]["renames"]),
    )


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Wrote %s", path)


# ---------------------------------------------------------------------------
# load command
# ---------------------------------------------------------------------------


def cmd_load(city: str) -> None:
    """Read seed JSON files and upsert into the database."""
    from app.core.config import settings

    engine = create_engine(settings.sync_database_url, echo=False)

    with Session(engine) as session:
        city_id = _ensure_city(session, city)
        _load_districts(session, city_id, city)
        _load_street_renames(session, city_id, city)
        session.commit()

    logger.info("Load complete for city: %s", city)


def _ensure_city(session: Session, city: str) -> int:
    """Insert city row if absent; return its id."""
    defaults = CITY_DEFAULTS.get(city)
    if not defaults:
        raise ValueError(f"No default config for city '{city}'. Add it to CITY_DEFAULTS.")

    city_name = defaults["name"]
    row = session.execute(text("SELECT id FROM cities WHERE name = :name"), {"name": city_name}).fetchone()
    if row:
        logger.info("City '%s' already exists (id=%d)", city, row[0])
        return int(row[0])

    result = session.execute(
        text(
            "INSERT INTO cities (name, name_ru, bbox_north, bbox_south, bbox_east, bbox_west, default_zoom)"
            " VALUES (:name, :name_ru, :bbox_north, :bbox_south, :bbox_east, :bbox_west, :default_zoom)"
            " RETURNING id"
        ),
        defaults,
    )
    city_id = int(result.scalar_one())
    logger.info("Inserted city '%s' (id=%d)", city, city_id)
    return city_id


def _load_districts(session: Session, city_id: int, city: str) -> None:
    path = DATA_DIR / "districts.json"
    if not path.exists():
        logger.warning("districts.json not found — skipping district load")
        return

    data = json.loads(path.read_text(encoding="utf-8"))
    records = data.get("districts", [])
    inserted = updated = skipped = 0

    for rec in records:
        existing = session.execute(
            text("SELECT id FROM districts WHERE city_id = :city_id AND name = :name"),
            {"city_id": city_id, "name": rec["name_uk"]},
        ).fetchone()

        polygon_wkt = _polygon_to_wkt(rec["polygon"])
        if polygon_wkt is None:
            logger.debug("Skipping district with invalid polygon: %s", rec["name_uk"])
            skipped += 1
            continue

        if existing:
            session.execute(
                text(
                    "UPDATE districts SET name_ru = :name_ru, polygon = ST_GeomFromText(:polygon, 4326) WHERE id = :id"
                ),
                {"name_ru": rec["name_ru"], "polygon": polygon_wkt, "id": existing[0]},
            )
            updated += 1
        else:
            session.execute(
                text(
                    "INSERT INTO districts (city_id, name, name_ru, polygon)"
                    " VALUES (:city_id, :name, :name_ru, ST_GeomFromText(:polygon, 4326))"
                ),
                {
                    "city_id": city_id,
                    "name": rec["name_uk"],
                    "name_ru": rec["name_ru"],
                    "polygon": polygon_wkt,
                },
            )
            inserted += 1

    logger.info("Districts: inserted=%d updated=%d skipped=%d", inserted, updated, skipped)


def _load_street_renames(session: Session, city_id: int, city: str) -> None:
    path = DATA_DIR / "street_renames.json"
    if not path.exists():
        logger.warning("street_renames.json not found — skipping rename load")
        return

    data = json.loads(path.read_text(encoding="utf-8"))
    records = data.get("renames", [])
    inserted = updated = skipped = 0

    for rec in records:
        existing = session.execute(
            text("SELECT id, status FROM street_renames WHERE city_id = :city_id AND old_name_uk = :old_name_uk"),
            {"city_id": city_id, "old_name_uk": rec["old_name_uk"]},
        ).fetchone()

        if existing:
            # Preserve records that an admin has already reviewed (status != 'pending')
            if existing[1] != "pending":
                logger.debug(
                    "Skipping rename '%s' — admin-modified (status=%s)",
                    rec["old_name_uk"],
                    existing[1],
                )
                skipped += 1
                continue
            # Re-seed pending records (overwrite with latest OSM data)
            session.execute(
                text(
                    "UPDATE street_renames"
                    " SET old_name_ru = :old_name_ru, new_name_uk = :new_name_uk,"
                    "     new_name_ru = :new_name_ru, year_renamed = :year_renamed"
                    " WHERE id = :id"
                ),
                {
                    "old_name_ru": rec.get("old_name_ru"),
                    "new_name_uk": rec["new_name_uk"],
                    "new_name_ru": rec.get("new_name_ru"),
                    "year_renamed": rec.get("year_renamed"),
                    "id": existing[0],
                },
            )
            updated += 1
        else:
            session.execute(
                text(
                    "INSERT INTO street_renames"
                    " (city_id, old_name_uk, old_name_ru, new_name_uk, new_name_ru, year_renamed, status)"
                    " VALUES (:city_id, :old_name_uk, :old_name_ru, :new_name_uk, :new_name_ru,"
                    "         :year_renamed, 'pending')"
                ),
                {
                    "city_id": city_id,
                    "old_name_uk": rec["old_name_uk"],
                    "old_name_ru": rec.get("old_name_ru"),
                    "new_name_uk": rec["new_name_uk"],
                    "new_name_ru": rec.get("new_name_ru"),
                    "year_renamed": rec.get("year_renamed"),
                },
            )
            inserted += 1

    logger.info("Street renames: inserted=%d updated=%d preserved=%d", inserted, updated, skipped)


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def _polygon_to_wkt(coords: list[list[float]]) -> str | None:
    """Convert [[lat, lng], ...] to a WKT POLYGON string (longitude first per WKS-84)."""
    if not coords or len(coords) < 3:  # noqa: PLR2004
        return None

    # PostGIS expects (lng lat) order
    points = [f"{c[1]} {c[0]}" for c in coords]

    # Ensure ring is closed
    if points[0] != points[-1]:
        points.append(points[0])

    return f"POLYGON(({', '.join(points)}))"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    city_arg = argparse.ArgumentParser(add_help=False)
    city_arg.add_argument("--city", default="odesa", help="Target city slug (default: odesa)")

    parser = argparse.ArgumentParser(
        description="WontHurtMaps seed data pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("generate", parents=[city_arg], help="Extract OSM data and write JSON seed files")
    sub.add_parser("load", parents=[city_arg], help="Upsert seed JSON files into the database")

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "generate":
        cmd_generate(args.city)
    elif args.command == "load":
        cmd_load(args.city)


if __name__ == "__main__":
    main()
