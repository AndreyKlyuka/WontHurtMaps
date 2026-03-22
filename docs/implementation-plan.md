# WontHurtMaps — Implementation Plan

## Overview

Phased implementation plan for the MVP based on the [MVP Design Document](./mvp-design-plan.md). Each phase is a logically complete block that can be deployed and tested independently.

**Estimated scope:** ~6 phases, each building on the previous one.

---

## Phase 0: Project Scaffolding & Infrastructure

**Goal:** Set up the development environment, CI, and base project structure.

### 0.1 Backend (Python/FastAPI)
- [ ] Initialize Python project (pyproject.toml / Poetry or uv)
- [ ] Package structure: `app/api/`, `app/worker/`, `app/core/`, `app/models/`, `app/services/`
- [ ] Set up FastAPI entry point (`app/api/main.py`)
- [ ] Set up Worker entry point (`app/worker/main.py`)
- [ ] Base configuration via pydantic-settings (ENV vars)
- [ ] Dockerfile for API and Worker
- [ ] Docker Compose: API + Worker + PostgreSQL/PostGIS + Photon

### 0.2 Frontend (Angular)
- [ ] Initialize Angular project (standalone components, no SSR needed)
- [ ] Install dependencies: Leaflet, leaflet.heat, leaflet.markercluster
- [ ] Base structure: `core/`, `features/map/`, `features/admin/`, `shared/`
- [ ] Proxy config for API (development)
- [ ] Dockerfile for frontend (nginx + build)
- [ ] Add to docker-compose

### 0.3 Database
- [ ] PostgreSQL + PostGIS in docker-compose
- [ ] Alembic for migrations
- [ ] Initial migration: create all tables per Design Document schema
  - `cities`, `posts`, `locations`, `slang_dictionary`, `street_renames`
  - `channel_state`, `geocode_cache`, `districts`, `unrecognized_tokens`, `worker_heartbeat`
- [ ] Seed data: Odesa city (name, bbox, default_zoom)
- [ ] Spatial indexes on `locations.geometry`

### 0.4 External Services
- [ ] Photon: docker image with Ukraine extract, port configuration
- [ ] Verify Photon API availability (`localhost:2322`)

### 0.5 Docker & Deployment Setup

**Development mode:** only infrastructure services run in Docker (db, photon). Backend and frontend run locally for fast feedback loop (hot reload, debugger).

**Production mode:** everything runs in Docker via `docker-compose.yml`. Target: VPS (Hetzner/DigitalOcean, 4GB RAM) with reverse proxy + SSL.

#### Backend Dockerfile (`docker/backend.Dockerfile`)
- Multi-stage build:
  - **Stage 1 (builder):** `python:3.12-slim` → install `uv`, copy `pyproject.toml` + `uv.lock` → `uv sync` (dependencies cached in layer) → copy source code
  - **Stage 2 (runtime):** `python:3.12-slim` → copy venv from builder → non-root user (`appuser`) → `EXPOSE 8000`
- Single Dockerfile, two entrypoints:
  - API: `uvicorn app.api.main:app --host 0.0.0.0 --port 8000`
  - Worker: `python -m app.worker`
- No spaCy models baked into image — downloaded on first run or via init script (keeps image smaller, models versioned separately)

#### Frontend Dockerfile (`docker/frontend.Dockerfile`)
- Multi-stage build:
  - **Stage 1 (builder):** `node:20-alpine` → copy `package.json` + `package-lock.json` → `npm ci` → copy source → `ng build --configuration=production`
  - **Stage 2 (runtime):** `nginx:alpine` → copy build output from builder to `/usr/share/nginx/html` → custom `nginx.conf` (SPA fallback, API proxy pass, gzip, cache headers)
- Resulting image: ~30MB

#### docker-compose.yml
```yaml
services:
  db:
    image: postgis/postgis:16-3.4
    volumes: [pgdata:/var/lib/postgresql/data]
    environment: [POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD]
    ports: ["5432:5432"]  # dev only, removed in prod
    healthcheck: pg_isready

  photon:
    image: komoot/photon
    volumes: [photon_data:/photon/photon_data]
    ports: ["2322:2322"]
    # First run: import Ukraine extract (see 0.4)

  api:
    build: { dockerfile: docker/backend.Dockerfile }
    command: uvicorn app.api.main:app --host 0.0.0.0 --port 8000
    depends_on: { db: { condition: service_healthy } }
    environment: [DATABASE_URL, TELEGRAM_API_ID, TELEGRAM_API_HASH, JWT_SECRET]
    ports: ["8000:8000"]

  worker:
    build: { dockerfile: docker/backend.Dockerfile }
    command: python -m app.worker
    depends_on: { db: { condition: service_healthy }, photon: { condition: service_started } }
    environment: [DATABASE_URL, TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION]
    volumes: [telegram_sessions:/app/sessions]  # Telethon session persistence

  frontend:
    build: { dockerfile: docker/frontend.Dockerfile }
    ports: ["80:80"]
    depends_on: [api]

volumes:
  pgdata:
  photon_data:
  telegram_sessions:
```

#### Environment & Secrets
- `.env` file for local development (git-ignored)
- `.env.example` committed with placeholder values
- Production: env vars set on VPS directly or via deployment script
- Sensitive values: `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION`, `JWT_SECRET`, `POSTGRES_PASSWORD`

#### Production Extras (post-MVP, not in Phase 0)
- Nginx reverse proxy with Let's Encrypt SSL (Caddy or nginx-proxy + acme-companion)
- `restart: unless-stopped` on all services
- Log rotation for containers
- Backup script for PostgreSQL volume

### Deliverable
Docker-compose up brings all services online. API responds to health check. Frontend shows an empty page with a map. DB with all tables created.

---

## Phase 1: Telegram Fetcher & Data Ingestion

**Goal:** Fetch posts from Telegram channel and store them in the database.

### 1.1 Telegram Client
- [ ] Telethon client with session persistence
- [ ] Configuration: API ID, API Hash, phone/session via ENV
- [ ] Authorization and session file storage

### 1.2 Fetcher Service
- [ ] Incremental fetching: `last_message_id` from `channel_state`
- [ ] Bootstrap mode: fetch last N messages on first run
- [ ] Batch fetching (100 messages per request)
- [ ] Deduplication by `telegram_id`
- [ ] Rate limit handling: `FloodWaitError` → wait + retry
- [ ] Exponential backoff on network errors (3 attempts)
- [ ] Save raw post to `posts` table with status `pending`

### 1.3 Deleted Post Tracking
- [ ] Handle `DeletedMessage` events
- [ ] Soft-delete: `is_deleted = true`

### 1.4 Worker Integration
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

### 2.3 Location Analyzer — spaCy NER (fallback)
- [ ] spaCy `uk_core_news_sm` / `ru_core_news_sm`
- [ ] LOC/GPE entity extraction
- [ ] Validate extracted entities against city dictionaries
- [ ] Confidence penalty (x 0.5) for NER-only results

### 2.4 Unrecognized Token Logging
- [ ] Save unrecognized tokens to `unrecognized_tokens`
- [ ] Increment `occurrence_count` for known tokens
- [ ] Store `sample_post_ids` (up to 5)

### 2.5 Geocoder
- [ ] Geocode cache lookup
- [ ] Street rename mapping (`street_renames` table)
- [ ] Photon geocoding (primary)
- [ ] Nominatim geocoding (fallback) with rate-limit queue (1 req/sec, token bucket)
- [ ] District/landmark dictionary with fixed coordinates
- [ ] Bounding box validation (city bbox)
- [ ] Out-of-bounds handling: try next fallback, save with `out_of_bounds = true`
- [ ] Queue overflow protection (max 500, remainder stays `pending` until next cycle)

### 2.6 Data Normalizer
- [ ] Determine geometry type (Point/Polygon)
- [ ] `geo_type` metadata (point/street/area/district)
- [ ] Confidence scoring: `(extraction_score * 0.5) + (geocoder_score * 0.5)`
- [ ] Slang candidate tracking (pending entries in `slang_dictionary`)
- [ ] Save to `locations` table
- [ ] Low confidence → `status = unresolved`

### 2.7 Pipeline Orchestration
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

### 4.4 Admin Frontend — Unresolved Posts
- [ ] `AdminUnresolvedComponent` (`/admin/unresolved`)
- [ ] Table with raw text, suggested location, post date
- [ ] Mini-map per post for manual resolution
- [ ] Confirm / Edit / Reject actions

### 4.5 Admin Frontend — Dictionary Management
- [ ] `AdminDictionaryComponent` (`/admin/dictionary`)
- [ ] Tabs: Pending / Active / Rejected
- [ ] Approve / Edit / Reject actions
- [ ] Unrecognized tokens section

### Deliverable
Full admin panel: dashboard with counters, unresolved post management, dictionary management, worker monitoring.

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
2. Code is covered by tests (unit + integration where appropriate)
3. Docker compose brings up all services without errors
4. Documentation updated as needed
