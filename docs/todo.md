# Phase 1: Telegram Fetcher & Data Ingestion

## 1.1 Telegram Auth Script

- [x] Create `scripts/telegram_auth.py` — interactive CLI for first-time Telegram auth (phone -> code -> optional 2FA)
- [x] Session file saved to `sessions/telegram.session`
- [x] Ensure `sessions/` directory is git-ignored (verify `.gitignore`)
- [x] Verify: run script, complete auth flow, session file is persisted

## 1.2 Telegram Client Service

- [x] Create `app/services/telegram_client.py` — Telethon client wrapper
- [x] Initialize client from `settings.telegram_api_id` + `settings.telegram_api_hash`
- [x] Session path: configurable via `settings.telegram_session_path`
- [x] `connect()` method — start client, handle auth errors (missing/expired session)
- [x] `disconnect()` method — graceful shutdown
- [x] Auth error handling: if session invalid/missing, log warning, raise custom exception
- [x] Add `TelegramAuthError` to `app/core/exceptions.py`

## 1.3 Channel Resolution

- [x] Create `app/repositories/channel_state_repository.py` with `get_active_channel()` and `update_last_message_id()`
- [x] Create `app/services/channel_resolver.py`
- [x] `resolve_channel()`: read active channel from `channel_state` table (`is_active=True`)
- [x] Dev fallback: if no channel in DB, read `settings.telegram_channel_name` from ENV
- [x] If neither DB nor ENV has channel — use hardcoded fallback `"Не повредит, Одесса"`; return `None` if not found in dialogs (worker enters idle mode)
- [x] Resolve channel title via `iter_dialogs()` -> persist to DB as new `ChannelState` row

## 1.4 Fetcher Service

- [x] Create `app/services/fetcher.py` — main fetch logic
- [x] `fetch_new_posts(channel_id, last_message_id)` method
- [x] Incremental fetching: use `last_message_id` from `channel_state` as offset
- [x] Bootstrap mode: if `last_message_id == 0`, fetch last N messages (`settings.telegram_bootstrap_limit`)
- [x] Batch fetching: iterate Telethon messages with `limit=100` per request
- [x] Map Telethon message -> Post fields (`telegram_id`, `channel_id`, `raw_text`, `post_date`)
- [x] Filter: skip messages without text content (media-only, service messages)
- [x] Return list of new post dicts for persistence

## 1.5 Fetcher Rate Limit & Error Handling

- [x] Handle Telethon `FloodWaitError` — wait specified seconds + retry (capped at 300s)
- [x] Exponential backoff on network errors (3 attempts, base 5s)
- [x] Log each retry attempt with context (`attempt`, `wait_time`, `error`)
- [x] On permanent failure (3 retries exhausted) — log error, return partial results collected so far

## 1.6 Post Repository

- [x] Create `app/repositories/post_repository.py`
- [x] `bulk_save_posts(posts: list[dict])` — bulk insert with deduplication by `telegram_id` (ON CONFLICT DO NOTHING)
- [x] `mark_deleted(telegram_ids: list[int])` — soft-delete: set `is_deleted=True`
- [x] `get_pending_posts(limit: int)` — fetch posts with `status='pending'` (interface for Phase 2)

## 1.7 Deleted Post Tracking

- [x] Detect deleted messages during fetch cycle via `DeletedPostsTracker` service
- [x] On deleted message detection: call `post_repository.mark_deleted([telegram_id])`
- [x] Log deleted post IDs at INFO level
- [x] Tracker runs unconditionally each cycle (not only when new posts are fetched)

## 1.8 Worker Pipeline Integration

- [x] Refactor `app/worker/main.py` — replace placeholder `run_pipeline()` with actual fetch stage
- [x] On startup: initialize Telegram client (`connect()`)
- [x] On shutdown: disconnect Telegram client
- [x] `run_pipeline()` flow: resolve channel -> fetch new posts -> save to DB -> update `last_message_id`
- [x] If no channel resolved — log warning, skip cycle (idle mode)
- [x] If Telegram auth fails — log error, skip cycle, do not crash

## 1.9 Advisory Lock & Concurrency

- [x] Add `pg_try_advisory_xact_lock(hash)` at start of `run_pipeline()` — prevent parallel execution
- [x] If lock not acquired — log info, skip cycle
- [x] Transaction-level lock auto-releases on commit (no explicit release needed)

## 1.10 Worker Heartbeat

- [x] Create `app/repositories/heartbeat_repository.py`
- [x] `upsert_heartbeat(status, current_job, posts_processed)` — insert or update single heartbeat row
- [x] Update heartbeat at: pipeline start (`status='running'`), pipeline end (`status='idle'`)
- [x] Heartbeat includes `posts_processed` count from current cycle

## 1.11 Pipeline Cycle Logging

- [x] Log at INFO: cycle start, channel resolved, messages fetched count, posts saved count, cycle duration
- [x] Log at WARNING: no channel configured, auth failure, rate limit hit
- [x] Log at ERROR: unrecoverable fetch errors, DB write failures
- [x] Include structured context in log messages (`extra={"channel_id": ..., "cycle_id": ...}`)

## 1.12 Config Additions

- [x] Add `telegram_session_path: str = "sessions/telegram.session"` to `Settings`
- [x] Add `telegram_bootstrap_limit: int = 500` to `Settings`
- [x] Update `.env.example` with new settings

## 1.13 Verification & Phase Completion

- [x] Start DB via `docker compose up db`
- [x] Run `alembic upgrade head` — confirm migrations apply
- [x] Run `scripts/telegram_auth.py` — confirm session is created
- [x] Start worker (`python -m app.worker`) — confirm it connects to Telegram
- [x] Verify: worker fetches posts from channel and saves to `posts` table (499 posts saved)
- [x] Verify: on restart, worker resumes from `last_message_id` (no duplicates)
- [x] Verify: heartbeat row is updated in `worker_heartbeat` table
- [x] Verify: `ruff check --fix . && ruff format .` passes
- [x] Verify: `mypy app/core/ app/services/` passes
- [x] Mark Phase 1 as completed in `docs/implementation-plan.md`

---

## New Files

| File                                           | Purpose                                    |
| ---------------------------------------------- | ------------------------------------------ |
| `scripts/telegram_auth.py`                     | Interactive Telegram auth CLI              |
| `app/services/telegram_client.py`              | Telethon client wrapper                    |
| `app/services/channel_resolver.py`             | Channel resolution via dialog title search |
| `app/services/fetcher.py`                      | Post fetching from Telegram                |
| `app/services/deleted_posts_tracker.py`        | Deleted post detection and soft-delete     |
| `app/repositories/channel_state_repository.py` | ChannelState DB access                     |
| `app/repositories/post_repository.py`          | Post DB access                             |
| `app/repositories/heartbeat_repository.py`     | WorkerHeartbeat DB access                  |
| `app/repositories/advisory_lock.py`            | PostgreSQL transaction-level advisory lock |

## Modified Files

| File                          | Changes                                                                 |
| ----------------------------- | ----------------------------------------------------------------------- |
| `app/worker/main.py`          | Real pipeline integration, Telegram lifecycle, asyncio.run() fix        |
| `app/core/config.py`          | `telegram_session_path`, `telegram_bootstrap_limit`, absolute .env path |
| `app/core/exceptions.py`      | `TelegramAuthError` with detail parameter                               |
| `app/models/channel_state.py` | `channel_name` column, UNIQUE constraint on `channel_id`                |
| `app/api/routers/admin.py`    | JWT auth, login endpoint                                                |
| `docker-compose.yml`          | `TELEGRAM_CHANNEL_NAME` env var                                         |
| `.env.example`                | New settings                                                            |

## Migrations

| Migration | Change                                              |
| --------- | --------------------------------------------------- |
| `0002`    | Rename `channel_link` → `channel_name`              |
| `0003`    | Add UNIQUE constraint on `channel_state.channel_id` |
