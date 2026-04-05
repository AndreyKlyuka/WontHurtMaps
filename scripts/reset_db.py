"""Reset database: truncate all application data while preserving schema and migrations.

Usage:
    python scripts/reset_db.py [--confirm]

WARNING: This is a destructive, irreversible operation. All application data will be deleted.
Schema (tables, indexes, constraints) and the Alembic migration version are preserved.

See docs/dev-operations.md for full documentation.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).parent
_BACKEND_DIR = _SCRIPTS_DIR.parent / "backend"
sys.path.insert(0, str(_BACKEND_DIR))

from sqlalchemy import create_engine, text  # noqa: E402

from app.core.config import settings  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Tables to truncate in FK-safe order (most-dependent first).
# cities is intentionally excluded — it holds stable seed data (city names, bbox).
# alembic_version is excluded — schema state must be preserved.
_TRUNCATE_TABLES = [
    "locations",
    "unrecognized_tokens",
    "geocode_cache",
    "slang_dictionary",
    "street_renames",
    "worker_heartbeat",
    "channel_state",
    "posts",
]


def reset(*, dry_run: bool = False) -> None:
    engine = create_engine(settings.sync_database_url, echo=False)

    tables_csv = ", ".join(_TRUNCATE_TABLES)
    sql = f"TRUNCATE TABLE {tables_csv} RESTART IDENTITY CASCADE"

    if dry_run:
        logger.info("[dry-run] Would execute: %s", sql)
        return

    with engine.begin() as conn:
        conn.execute(text(sql))

    logger.info("Reset complete. Truncated tables: %s", tables_csv)


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset WontHurtMaps database (data only, schema preserved).")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required flag to confirm the destructive operation.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be executed without making changes.",
    )
    args = parser.parse_args()

    if args.dry_run:
        reset(dry_run=True)
        return

    if not args.confirm:
        print("ERROR: This operation deletes all application data.")
        print("Re-run with --confirm to proceed:")
        print("  python scripts/reset_db.py --confirm")
        sys.exit(1)

    reset(dry_run=False)


if __name__ == "__main__":
    main()
