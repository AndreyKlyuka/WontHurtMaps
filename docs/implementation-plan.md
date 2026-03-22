# WontHurtMaps — Implementation Plan

## Overview

Phased implementation plan for the MVP based on the [MVP Design Document](./mvp-design-plan.md). Each phase is a logically complete block that can be deployed and tested independently.

**Estimated scope:** ~6 phases, each building on the previous one.

---

## Phase 0: Project Scaffolding & Infrastructure

**Goal:** Set up the development environment, CI, and base project structure.

### Monorepo Structure

```
wonthurtmaps/
  backend/           ← Python: FastAPI API + Worker
    app/
      api/
      worker/
      core/
      models/
      services/
    pyproject.toml
  frontend/          ← Angular 21
    src/app/
      core/
      features/map/
      features/admin/
      shared/
    package.json
  scripts/           ← Seed data, Telegram auth
  data/seed/         ← Generated & static seed data (JSON)
  docker/            ← Dockerfiles
  docs/              ← Project documentation
  docker-compose.yml
  .env.example
  .editorconfig
  package.json       ← Root: husky + lint-staged only
```

### 0.1 Backend (Python/FastAPI)
- [ ] Initialize Python project (pyproject.toml / Poetry or uv)
- [ ] Package structure: `backend/app/api/`, `backend/app/worker/`, `backend/app/core/`, `backend/app/models/`, `backend/app/services/`
- [ ] Set up FastAPI entry point (`backend/app/api/main.py`)
- [ ] Set up Worker entry point (`backend/app/worker/main.py`)
- [ ] Base configuration via pydantic-settings (ENV vars)
- [ ] Dockerfile for API and Worker
- [ ] CORS middleware: allow `localhost:4200` in dev (Angular dev server), restrictive in production
- [ ] Docker Compose: API + Worker + PostgreSQL/PostGIS

### 0.2 Frontend (Angular)
- [ ] Initialize Angular 21 project in `frontend/` (standalone components, no SSR needed)
- [ ] Install dependencies: Leaflet, leaflet.heat, leaflet.markercluster
- [ ] Base structure: `frontend/src/app/core/`, `frontend/src/app/features/map/`, `frontend/src/app/features/admin/`, `frontend/src/app/shared/`
- [ ] Proxy config for API (development)
- [ ] Dockerfile for frontend (nginx + build)
- [ ] Add to docker-compose

### 0.3 Database
- [ ] PostgreSQL + PostGIS in docker-compose
- [ ] Alembic for migrations (autogenerate from SQLAlchemy models)
- [ ] Initial migration: create all tables per Design Document schema
  - `cities`, `posts`, `locations`, `slang_dictionary`, `street_renames`
  - `channel_state`, `geocode_cache`, `districts`, `unrecognized_tokens`, `worker_heartbeat`
- [ ] Seed data: Odesa city (name, bbox, default_zoom)
- [ ] Spatial indexes on `locations.geometry`

### 0.4 External Services
- [ ] Nominatim public API as sole geocoder for MVP (no local Photon)
- [ ] Geocode cache (DB-based, 90-day TTL) to minimize Nominatim requests
- [ ] Rate limiter: 1 req/sec to Nominatim (token bucket)
- [ ] Post-MVP: add local Photon instance if Nominatim rate limit becomes a bottleneck

### 0.4.1 Seed Data Pipeline
- [ ] `scripts/seed_data.py` — main orchestrator with `generate` and `load` commands
- [ ] `scripts/osm_extractor.py` — Overpass API queries for streets, districts, renames
- [ ] `scripts/ru_name_generator.py` — rule-based Ukrainian → Russian name transformation
- [ ] `data/seed/abbreviations.json` — static abbreviation list (committed to git)
- [ ] Extract streets from OSM: `name`, `name:ru`, `old_name`, centroid coordinates
- [ ] Generate Russian names for streets missing `name:ru` via rule-based transformation
- [ ] Extract district polygons from OSM (`boundary=administrative`, `place=suburb/quarter`)
- [ ] Extract street renames from OSM `old_name` tags → `status=pending` in DB
- [ ] `load` command: idempotent upsert into DB, preserves admin-modified records
- [ ] Verify: seed data loaded correctly, streets available for fuzzy matching

See [Seed Data Pipeline Design](./seed-data-pipeline-design.md) for details.

### 0.5 Docker & Deployment Setup

**Development mode:** only infrastructure services run in Docker (db). Backend and frontend run locally for fast feedback loop (hot reload, debugger).

**Production mode:** everything runs in Docker via `docker-compose.yml`. Target: VPS (Hetzner/DigitalOcean, 4GB RAM) with reverse proxy + SSL.

#### Backend Dockerfile (`docker/backend.Dockerfile`)
- Multi-stage build:
  - **Stage 1 (builder):** `python:3.12-slim` → install `uv`, copy `pyproject.toml` + `uv.lock` → `uv sync` (dependencies cached in layer) → copy source code
  - **Stage 2 (runtime):** `python:3.12-slim` → copy venv from builder → non-root user (`appuser`) → `EXPOSE 8000`
- Single Dockerfile, two entrypoints:
  - API: `uvicorn app.api.main:app --host 0.0.0.0 --port 8000`
  - Worker: `python -m app.worker`
- No NLP models in MVP image — spaCy/LLM deferred to post-MVP

#### Frontend Dockerfile (`docker/frontend.Dockerfile`)
- Multi-stage build:
  - **Stage 1 (builder):** `node:20-alpine` → copy `package.json` + `package-lock.json` → `npm ci` → copy source → `ng build --configuration=production`
  - **Stage 2 (runtime):** `nginx:alpine` → copy build output from builder to `/usr/share/nginx/html` → custom `nginx.conf` (SPA fallback, API proxy pass, gzip, cache headers)
- Resulting image: ~30MB

#### docker-compose.yml
```yaml
services:
  db:
    image: postgis/postgis:17-3.5
    volumes: [pgdata:/var/lib/postgresql/data]
    environment: [POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD]
    ports: ["5432:5432"]  # dev only, removed in prod
    healthcheck: pg_isready

  api:
    build: { context: ./backend, dockerfile: ../docker/backend.Dockerfile }
    command: uvicorn app.api.main:app --host 0.0.0.0 --port 8000
    depends_on: { db: { condition: service_healthy } }
    environment: [DATABASE_URL, TELEGRAM_API_ID, TELEGRAM_API_HASH, JWT_SECRET]
    ports: ["8000:8000"]

  worker:
    build: { context: ./backend, dockerfile: ../docker/backend.Dockerfile }
    command: python -m app.worker
    depends_on: { db: { condition: service_healthy } }
    environment: [DATABASE_URL, TELEGRAM_API_ID, TELEGRAM_API_HASH]
    volumes: [telegram_sessions:/app/sessions]  # Telethon session persistence

  frontend:
    build: { context: ./frontend, dockerfile: ../docker/frontend.Dockerfile }
    ports: ["80:80"]
    depends_on: [api]

volumes:
  pgdata:
  telegram_sessions:
```

#### Environment & Secrets
- `.env` file for local development (git-ignored)
- `.env.example` committed with placeholder values
- Production: env vars set on VPS directly or via deployment script
- Session file: `sessions/telegram.session` — created by `scripts/telegram_auth.py`, mounted as Docker volume, never in git

**`.env.example` contents:**
```env
# Database
POSTGRES_DB=wonthurtmaps
POSTGRES_USER=wonthurt
POSTGRES_PASSWORD=changeme
DATABASE_URL=postgresql://wonthurt:changeme@localhost:5432/wonthurtmaps

# Telegram API (https://my.telegram.org)
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=your_api_hash_here

# Telegram channel (dev-only fallback, production uses admin panel)
TELEGRAM_CHANNEL_LINK=

# Auth
JWT_SECRET=changeme_generate_random_string
ADMIN_USERNAME=admin
ADMIN_PASSWORD=changeme

# API
API_HOST=0.0.0.0
API_PORT=8000
CORS_ORIGINS=http://localhost:4200

# Worker
PIPELINE_INTERVAL_MINUTES=60
NOMINATIM_RATE_LIMIT=1.0
NOMINATIM_QUEUE_MAX=500
```

#### Production Extras (post-MVP, not in Phase 0)
- Nginx reverse proxy with Let's Encrypt SSL (Caddy or nginx-proxy + acme-companion)
- `restart: unless-stopped` on all services
- Log rotation for containers
- Backup script for PostgreSQL volume

### 0.6 Developer Experience Tooling

**Goal:** Consistent code style, automated checks on commit, unified editor settings across the monorepo.

#### EditorConfig (root)
- [ ] `.editorconfig` at project root — indent style, charset, trailing whitespace, final newline
- [ ] Settings: `indent_size = 2` for frontend (ts, html, scss, json, yaml), `indent_size = 4` for Python

#### Frontend (Angular) — ESLint + Prettier
- [ ] `angular-eslint` — installed via `ng add @angular-eslint/schematics`
- [ ] `eslint-config-prettier` + `eslint-plugin-prettier` — Prettier as ESLint rule (single pass)
- [ ] `.prettierrc` — config: `singleQuote: true`, `trailingComma: 'all'`, `printWidth: 120`
- [ ] `.prettierignore` — dist, coverage, node_modules
- [ ] Verify: `ng lint` runs ESLint + Prettier checks

#### Backend (Python) — Ruff
- [ ] `ruff` as dev dependency — linter + formatter in one tool (replaces black, flake8, isort)
- [ ] `ruff.toml` or `[tool.ruff]` section in `pyproject.toml`:
  - `line-length = 120`
  - `target-version = "py312"`
  - `select` — `E`, `F`, `W`, `I` (isort), `UP` (pyupgrade), `B` (bugbear), `SIM` (simplify)
  - `format.quote-style = "double"`
- [ ] `mypy` as dev dependency — strict type checking for core modules (`app/core/`, `app/services/`)
- [ ] `mypy` config in `pyproject.toml`: `strict = false`, `warn_return_any = true`, `disallow_untyped_defs` for selected packages

#### Git Hooks — Husky + lint-staged
- [ ] `husky` — install, `husky init`, `.husky/pre-commit` hook
- [ ] `lint-staged` config in root `package.json` (or `.lintstagedrc`):
  - `"*.{ts,html}"` → `eslint --fix`
  - `"*.{ts,html,scss,json,md,yaml}"` → `prettier --write`
  - `"*.py"` → `ruff check --fix && ruff format`
- [ ] Root `package.json` with `devDependencies` only (husky, lint-staged) — serves as monorepo hook anchor
- [ ] Verify: staged files are linted/formatted before commit; non-staged files are untouched

#### IDE Recommendations (WebStorm)
- [ ] `.idea/` added to `.gitignore` (except shared configs below)
- [ ] Shared run configurations in `.idea/runConfigurations/` (git-tracked): `ng serve`, `ruff check`, `docker-compose up`
- [ ] `.idea/codeStyles/` — project code style delegated to EditorConfig + Prettier + Ruff (no IDE-specific overrides)
- [ ] Verify: WebStorm picks up `.editorconfig`, Prettier config (built-in support), and ESLint config automatically
- [ ] Ruff plugin for WebStorm — external tool or file watcher for Python linting/formatting on save

### Deliverable
Docker-compose up brings all services online. API responds to health check. Frontend shows an empty page with a map. DB with all tables created. Pre-commit hooks enforce code style on every commit.

---

## Phase 1: Telegram Fetcher & Data Ingestion

**Goal:** Fetch posts from Telegram channel and store them in the database.

### 1.1 Telegram Client
- [ ] Telethon client with session persistence
- [ ] Configuration: API ID, API Hash via ENV
- [ ] `scripts/telegram_auth.py` — interactive CLI script for first-time auth (phone → code → optional 2FA)
- [ ] Session file stored in `sessions/` directory (git-ignored, Docker volume in production)
- [ ] Worker reads session from `sessions/telegram.session` on startup
- [ ] Auth error handling: log warning, worker enters idle mode until session is fixed

### 1.2 Channel Resolution
- [ ] Worker reads active channel from `channel_state` table
- [ ] Dev fallback: if no channel in DB, read `TELEGRAM_CHANNEL_LINK` from ENV
- [ ] If neither DB nor ENV has channel — worker starts in idle mode, logs warning
- [ ] Channel link resolution: parse t.me / web.telegram.org links → extract numeric channel_id via Telethon

### 1.3 Fetcher Service
- [ ] Incremental fetching: `last_message_id` from `channel_state`
- [ ] Bootstrap mode: fetch last N messages on first run
- [ ] Batch fetching (100 messages per request)
- [ ] Deduplication by `telegram_id`
- [ ] Rate limit handling: `FloodWaitError` → wait + retry
- [ ] Exponential backoff on network errors (3 attempts)
- [ ] Save raw post to `posts` table with status `pending`

### 1.4 Deleted Post Tracking
- [ ] Handle `DeletedMessage` events
- [ ] Soft-delete: `is_deleted = true`

### 1.5 Worker Integration
- [ ] APScheduler: hourly job
- [ ] Advisory lock (`pg_try_advisory_lock`) to prevent parallel execution
- [ ] Heartbeat: write to `worker_heartbeat` every 60 seconds
- [ ] Job timeout: 50 minutes

### Deliverable
Worker starts, connects to Telegram, fetches posts into DB. On restart, resumes from last message. Heartbeat written to DB.

---

## Phase 2: Text Processing Pipeline

**Goal:** Process post text — from preprocessing to geocoding.

### 2.1 Text Preprocessor
- [ ] Remove emoji, formatting artifacts
- [ ] Unicode normalization (е/ё, і/i)
- [ ] Replace slang from `slang_dictionary`
- [ ] Store `cleaned_text`

### 2.2 Location Analyzer — Rule-Based
- [ ] Abbreviation normalizer (вул., пр., бульв., пл., пров.)
- [ ] City dictionaries: streets, districts, landmarks (JSON for Odesa)
- [ ] Token-level fuzzy matching via `rapidfuzz`
- [ ] Two-tier threshold: >= 90% high confidence, 80-89% candidate with penalty
- [ ] Pattern-based extraction: `<street> + <number>`, `район + <name>`, `біля + <landmark>`
- [ ] Output: `location_type`, `address`, `landmarks`, `confidence`

### 2.3 Unrecognized Token Logging
- [ ] Save unrecognized tokens to `unrecognized_tokens`
- [ ] Increment `occurrence_count` for known tokens
- [ ] Store `sample_post_ids` (up to 5)

### 2.4 Geocoder
- [ ] Geocode cache lookup
- [ ] Street rename mapping (`street_renames` table, only active renames)
- [ ] Nominatim geocoding with rate-limit queue (1 req/sec, token bucket)
- [ ] District dictionary with fixed coordinates
- [ ] Bounding box validation (city bbox)
- [ ] Out-of-bounds handling: try next fallback, save with `out_of_bounds = true`
- [ ] Queue overflow protection (max 500, remainder stays `pending` until next cycle)
- [ ] 3 consecutive Nominatim failures → skip for remainder of cycle

### 2.5 Data Normalizer
- [ ] Determine geometry type (Point/Polygon)
- [ ] `geo_type` metadata (point/street/area/district)
- [ ] Confidence scoring: `(extraction_score * 0.5) + (geocoder_score * 0.5)`
- [ ] Slang candidate tracking (pending entries in `slang_dictionary`)
- [ ] Save to `locations` table
- [ ] Low confidence → `status = unresolved`

### 2.6 Pipeline Orchestration
- [ ] Batch processing (100 posts)
- [ ] Transaction with savepoint per post
- [ ] Failure handling: `status=failed`, `error_message`, `retry_count`
- [ ] Max 3 retries → `permanent_failure`
- [ ] Logging: pipeline duration, queue depth per cycle

### Deliverable
Worker full cycle: fetch → preprocess → analyze → geocode → normalize → save. Telegram posts are transformed into geolocations in DB. Unrecognized posts marked as unresolved.

---

## Phase 3: Public API & Map Frontend

**Goal:** Display data on an interactive map.

### 3.1 Public API Endpoints
- [ ] `GET /api/locations` — GeoJSON FeatureCollection, mandatory `bbox`, PostGIS `ST_Within`
- [ ] `GET /api/heatmap` — aggregated grid cells with time-decay intensity
- [ ] `GET /api/route/check` — OSRM routing + `ST_DWithin` proximity check
- [ ] `GET /api/stats` — counts per filter selection
- [ ] `GET /api/cities` — list of cities

### 3.2 API Performance
- [ ] In-memory response cache (query string key, TTL 10 min or invalidate on pipeline completion)
- [ ] Rate limiting via `slowapi` (60 req/min public, 120 req/min admin)
- [ ] Server-side clustering at zoom < 14 (PostGIS grid-based grouping)

### 3.3 Frontend — Map
- [ ] `MapComponent` with Leaflet + OSM light tiles
- [ ] Leaflet.markercluster for points
- [ ] leaflet.heat for heatmap layer
- [ ] Popup on click: address, date, excerpt, confidence, geo_type badge
- [ ] Display modes: Heatmap / Points & Streets / Districts

### 3.4 Frontend — Sidebar & Filters
- [ ] `FilterPanelComponent` — collapsible sidebar
- [ ] Date Range picker + quick buttons (Today/Week/Month/All)
- [ ] Display Mode toggle (radio)
- [ ] Confidence slider
- [ ] `StatsComponent` — live counts
- [ ] `FilterService` — shared state, emits changes

### 3.5 Frontend — Route Check
- [ ] `RouteCheckComponent` — input A/B, relevance hours
- [ ] OSRM route polyline display
- [ ] Intersection warnings visualization

### 3.6 Frontend — Performance
- [ ] Debounce filters (300ms) and map move (500ms)
- [ ] Lazy loading by zoom (heatmap at low zoom, points at high zoom)
- [ ] Cancel in-flight requests (RxJS `switchMap`)
- [ ] Data refresh: poll `/api/stats` every 5 minutes

### 3.7 Visual Style
- [ ] Swiss Minimal: system sans-serif, white background, #111 text
- [ ] Muted red for danger indicators
- [ ] Thin borders, no shadows, generous whitespace

### Deliverable
Public map with all filters, heatmap, clustering, route check. Fully functional frontend for end users.

---

## Phase 4: Admin Panel

**Goal:** Admin interface for system management.

### 4.1 Auth
- [ ] `POST /api/auth/login` — JWT authentication
- [ ] `AuthService` on frontend — token management
- [ ] Auth guard for admin routes
- [ ] Single admin account (MVP)

### 4.2 Admin API
- [ ] `GET /api/admin/unresolved` — paginated unresolved posts
- [ ] `POST /api/admin/unresolved/{id}/confirm` — confirm location
- [ ] `POST /api/admin/unresolved/{id}/edit` — manual correction + side effects (cache, slang)
- [ ] `POST /api/admin/unresolved/{id}/reject` — reject post
- [ ] `GET /api/admin/dictionary` — slang dictionary CRUD
- [ ] `POST /api/admin/dictionary/{id}/approve|edit|reject`
- [ ] `GET /api/admin/unrecognized-tokens` — top tokens
- [ ] `POST /api/admin/unrecognized-tokens/{id}/add-to-dictionary|dismiss`
- [ ] `GET /api/admin/stats` — processing statistics
- [ ] `POST /api/admin/pipeline/trigger` — manual pipeline trigger
- [ ] `GET /api/admin/worker/status` — worker health
- [ ] `POST /api/admin/posts/{id}/retry` — re-queue failed post

### 4.3 Admin Frontend — Dashboard
- [ ] `AdminDashboardComponent` (`/admin`)
- [ ] Needs attention (red): unresolved + permanent_failure + high-frequency tokens
- [ ] Pending review (yellow): pending slang + flagged locations + out_of_bounds
- [ ] System health (green/yellow/red): worker status, last pipeline time
- [ ] Processed today (info): posts, locations, cache hit rate
- [ ] Clickable counters → filtered lists

### 4.4 Admin Frontend — Processing Log & Unresolved Posts
- [ ] `AdminProcessingLogComponent` (`/admin/processing-log`)
- [ ] Feed of all processed posts with full decision chain (extraction → rename → geocode)
- [ ] Filterable by status, confidence, date
- [ ] Admin can validate/reject rename mappings, correct wrong location bindings
- [ ] `AdminUnresolvedComponent` (`/admin/unresolved`)
- [ ] Table with raw text, suggested location, post date
- [ ] Mini-map per post for manual resolution
- [ ] Confirm / Edit / Reject actions

### 4.5 Admin Frontend — Dictionary Management
- [ ] `AdminDictionaryComponent` (`/admin/dictionary`)
- [ ] Tabs: Pending / Active / Rejected
- [ ] Approve / Edit / Reject actions
- [ ] Unrecognized tokens section

### 4.6 Admin Frontend — Channel Management
- [ ] `AdminChannelComponent` (`/admin/channel`)
- [ ] Input field for Telegram link (t.me or web.telegram.org format)
- [ ] "Connect" button → calls `POST /api/admin/channel`, shows connection status
- [ ] Display: channel title, channel_id, is_active toggle, last fetch time
- [ ] MVP: single channel, future: list of channels with add/remove

### 4.7 Admin Frontend — Street Renames Validation
- [ ] Street renames section in admin panel (tab or separate page)
- [ ] Table of pending renames from seed data (old name → new name)
- [ ] Activate / Edit / Reject actions per rename
- [ ] Only active renames are used by the geocoder pipeline

### Deliverable
Full admin panel: dashboard with counters, processing log, unresolved post management, dictionary management, street renames validation, worker monitoring.

---

## Phase 5: Self-Learning & Refinement

**Goal:** Automatic dictionary learning, edge case handling, polish.

### 5.1 Self-Learning Dictionary
- [ ] Auto-learn workflow: detect → pending → 3+ confirmations → active
- [ ] `usage_count` tracking per mapping
- [ ] Auto-demotion: 90 days without usage → `pending`
- [ ] Admin-added entries (`auto_learned = false`) — always active

### 5.2 Street Rename Handling
- [ ] `street_renames` seed data for Odesa
- [ ] Geocoder: current name first → old name fallback
- [ ] Both names stored for search

### 5.3 Geocode Cache Management
- [ ] TTL: 90 days, refresh on hit
- [ ] Cache hit count tracking

### 5.4 Error Handling & Resilience
- [ ] Nominatim degradation: 3 consecutive failures → skip for cycle
- [ ] OSRM unavailable → HTTP 503 + user-friendly message
- [ ] Worker crash recovery: advisory lock auto-release

### 5.5 Monitoring & Logging
- [ ] Worker logs: pipeline duration, queue depth per cycle
- [ ] Admin stats endpoint: metrics for monitoring
- [ ] Scalability thresholds logging (pipeline duration > 30min warning)

### Deliverable
System self-learns, graceful degradation on external service failures, production-ready error handling.

---

## Dependency Graph

```
Phase 0 (Infrastructure)
   |
   +-- Phase 1 (Telegram Fetcher)
   |       |
   |       +-- Phase 2 (Processing Pipeline)
   |               |
   |               +-- Phase 3 (Public API & Map) ---- can start in parallel with mock data
   |               |
   |               +-- Phase 4 (Admin Panel) ---- requires API from Phase 3
   |                       |
   |                       +-- Phase 5 (Self-Learning & Refinement)
   |
   +-- Phase 3 (frontend scaffolding can start in parallel with Phase 1)
```

**Parallelization:**
- Frontend scaffolding (Phase 3.3-3.7) can start in parallel with Phase 1-2 using mock data
- Phase 3 (API) and Phase 4 (Admin API) can be partially developed in parallel
- Phase 5 depends on the full pipeline (Phase 2) and admin panel (Phase 4)

---

## Definition of Done per Phase

A phase is considered complete when:
1. All phase checkboxes are done
2. Docker compose brings up all services without errors
3. Documentation updated as needed

**Testing:** deferred to post-MVP. Manual verification during development.
