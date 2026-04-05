# Developer Operations

Runbook for common development operations: database management, environment setup, and maintenance tasks.

---

## Database Reset (data only)

Truncates all application data while preserving schema and Alembic migration state.

**When to use:**

- Before starting a new development phase with a clean slate
- After a botched migration experiment (schema is intact but data is inconsistent)
- When you need reproducible test conditions

**When NOT to use:**

- In production — ever
- When you actually need to fix a schema issue (use `alembic downgrade` instead)
- When you want to reset the schema too (use the full volume reset below)

**Command:**

```bash
python scripts/reset_db.py --confirm
```

**What it does:**

- `TRUNCATE ... RESTART IDENTITY CASCADE` on all application tables
- Preserves: `cities` (seed data), `alembic_version` (migration state), all table/index/constraint definitions
- Truncated tables: `locations`, `unrecognized_tokens`, `geocode_cache`, `slang_dictionary`, `street_renames`, `worker_heartbeat`, `channel_state`, `posts`

**Dry-run (shows SQL without executing):**

```bash
python scripts/reset_db.py --dry-run
```

**After reset:**

- Reload seed data: `python scripts/seed_data.py load --city odesa`
- Re-authenticate Telegram (if needed): `python scripts/telegram_auth.py`
- Start worker — it will bootstrap-fetch posts on first cycle

---

## Full Schema Reset (Docker volume)

Drops the entire PostgreSQL volume, then re-creates from scratch. Use when the schema itself is broken or migrations are out of sync.

**Command:**

```bash
docker compose down -v          # destroys pgdata volume — ALL data and schema lost
docker compose up db -d         # fresh PostgreSQL with empty cluster
cd backend
alembic upgrade head            # apply all migrations from scratch
python scripts/seed_data.py load --city odesa  # reload seed data
```

**After reset:** re-authenticate Telegram and restart worker (bootstrap fetch).

---

## Re-fetch Telegram Posts

The worker automatically bootstrap-fetches on first run (when `last_message_id = 0`).
After a DB reset, simply start the worker — it will fetch the last `telegram_bootstrap_limit` posts (default: 500).

```bash
cd backend
python -m app.worker
```

---

## Check Migration State

```bash
cd backend
alembic current    # show current revision in DB
alembic history    # show full migration chain
```

---

## Seed Data

Generate fresh OSM data and load into DB (idempotent — safe to re-run):

```bash
python scripts/seed_data.py generate --city odesa   # fetch from OSM Overpass API
python scripts/seed_data.py load --city odesa       # upsert into DB
```
