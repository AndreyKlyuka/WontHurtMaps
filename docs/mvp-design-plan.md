# WontHurtMaps — MVP Design Document

## Overview

System for parsing Telegram channel posts about dangerous locations in a city, extracting addresses via NLP analysis, geocoding them, and visualizing on an interactive map with heatmaps, points, streets, and districts.

**Primary city:** Odesa (architecturally city is a parameter — extensible to other cities).

**Data source:** Private Telegram channel, accessed via dedicated account (MTProto client).

**Post volume:** Tens of thousands existing posts, up to 1000+ new posts/day.

**Post language:** Mixed Ukrainian/Russian.

---

## Architecture

### Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Angular + Leaflet (OSM tiles) |
| Backend / API | Python, FastAPI |
| Telegram client | Telethon (MTProto) |
| Text analysis | Rule-based (primary) + spaCy NER (fallback) + city dictionaries |
| Geocoding | Photon (local, primary) + Nominatim (fallback) |
| Routing | OSRM (free) |
| Database | PostgreSQL + PostGIS |
| Scheduler | APScheduler (MVP), migration-ready for Celery + Redis |
| Auth | JWT (simple admin auth for MVP) |

### System Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        ANGULAR FRONTEND                         │
│  ┌──────────┐  ┌──────────────┐  ┌────────────┐  ┌──────────┐ │
│  │  Leaflet  │  │  Heatmap     │  │  Date/Mode │  │  Admin   │ │
│  │  Map      │  │  Layer       │  │  Filters   │  │  Panel   │ │
│  └──────────┘  └──────────────┘  └────────────┘  └──────────┘ │
└────────────────────────┬────────────────────────────────────────┘
                         │ REST API (JSON / GeoJSON)
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                     PYTHON BACKEND (FastAPI)                     │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────┐ │
│  │  Public API   │  │  Scheduler   │  │  Processing Pipeline   │ │
│  │  /api/*       │  │  (hourly)    │  │                        │ │
│  │               │  │              │  │  1. Telegram Fetcher   │ │
│  │  Admin API    │  │  Triggers    │  │  2. Text Preprocessor  │ │
│  │  /api/admin/* │──│─ pipeline ──▶│  │  3. NLP Analyzer       │ │
│  │  (JWT auth)   │  └──────────────┘  │  4. Geocoder           │ │
│  └──────────────┘                     │  5. Data Normalizer    │ │
│                                       └────────────────────────┘ │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │                    Service Layer                              ││
│  │  ┌─────────────┐ ┌──────────────┐ ┌────────────────────────┐││
│  │  │ SlangDict   │ │ StreetRename │ │ ConfidenceScorer       │││
│  │  │ Service     │ │ Service      │ │ Service                │││
│  │  │ (self-learn)│ │ (old→new)    │ │ (exact/street/area)    │││
│  │  └─────────────┘ └──────────────┘ └────────────────────────┘││
│  └──────────────────────────────────────────────────────────────┘│
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                  POSTGRESQL + PostGIS                            │
│  ┌──────────┐ ┌───────────┐ ┌──────────┐ ┌──────────────────┐  │
│  │ posts    │ │ locations │ │ slang_   │ │ street_renames   │  │
│  │ (raw)    │ │ (geo)     │ │ dict     │ │ (old → new)      │  │
│  └──────────┘ └───────────┘ └──────────┘ └──────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Processing Pipeline

When the system is active, it processes posts from the last hour on an hourly cycle.

### Pipeline Stages

**1. Telegram Fetcher**
- Telethon MTProto client with dedicated account
- Session persistence: Telethon session file stored on disk (`.session` file), auto-reloads on restart
- **Incremental fetching:** tracks `last_message_id` per channel (stored in DB). Each cycle fetches from `last_message_id + 1` to newest. Never relies on time-based "last hour" — prevents gaps and duplicates after downtime.
- On first run (no `last_message_id`): fetches last N messages (configurable, default 1000) to bootstrap
- After successful batch: updates `last_message_id` to highest fetched ID
- Saves raw post to `posts` table with status `pending`
- Deduplication by `telegram_id` as safety net (incremental fetch should prevent duplicates)
- **Deleted post tracking:**
  - Worker periodically checks for `DeletedMessage` events via Telethon
  - Deleted posts marked with `is_deleted = true` in DB (soft-delete, data preserved)
  - Deleted posts excluded from map display and heatmap calculations
  - Admin panel shows deleted posts with visual indicator for transparency
- **Telegram rate limit handling:**
  - `FloodWaitError` → respect Telegram's wait time, log warning, resume after delay
  - Fetch in small batches (100 messages per request) to avoid hitting limits
  - Exponential backoff on network errors (3 attempts)
  - Auth errors → log and alert, skip cycle

**2. Text Preprocessor**
- Remove emoji, formatting artifacts
- Normalize Unicode (е/ё, і/i)
- Replace known slang from `slang_dictionary`
- Clean text stored as `cleaned_text`

**3. Location Analyzer (rule-based primary, NER secondary)**

Analysis priority: rule-based system first, spaCy NER only as fallback for posts where rules found nothing.

**Step 1: Abbreviation normalizer**
- Expand known abbreviations before any matching:
  - `"ген."` → `"генерала"`, `"пр."` → `"проспект"`, `"бульв."` → `"бульвар"`
  - `"вул."` → `"вулиця"`, `"пров."` → `"провулок"`, `"пл."` → `"площа"`
- Configurable per-city abbreviation dictionary (JSON)

**Step 2: Rule-based extractor (primary)**
- Token-level fuzzy matching against city dictionaries (streets, districts, landmarks)
  - Each token and n-gram (2-3 tokens) matched via `rapidfuzz.fuzz.partial_ratio`
  - Two-tier threshold:
    - **≥ 90%** → high-confidence match, full extraction_score
    - **80–89%** → candidate match with confidence penalty (× 0.8). If multiple candidates in this range — disambiguate by context (nearby district/landmark tokens) or mark as ambiguous (lowest-scoring candidate wins only if no alternatives)
    - **< 80%** → no match
  - Example: "тиирова" → "Таїрова" (fuzzy), "7км" → "7-й кілометр" (alias dict)
- Pattern-based extraction:
  - `<street_name> + <number>` → exact address
  - `<street_name> + <landmark>` → approximate address
  - `<district_name>` → district area
  - `район/мікрорайон + <name>` → district
  - `біля/поруч/навпроти + <landmark>` → landmark proximity

**Step 3: spaCy NER (fallback only)**
- Runs only if Step 2 found no locations
- spaCy `uk_core_news_sm` / `ru_core_news_sm` for LOC/GPE entity extraction
- Extracted entities are validated against city dictionaries (token-level fuzzy)
- NER results without dictionary confirmation get confidence penalty (× 0.5)

**Step 4: Unrecognized token logging**
- If neither Step 2 nor Step 3 found locations, extract candidate tokens (nouns, capitalized words, n-grams not in stop-list) and save to `unrecognized_tokens` table
- Each unique token tracked with `occurrence_count` — incremented on every new post containing it
- Admin panel shows top unrecognized tokens sorted by frequency → quick path to expanding dictionaries
- Tokens that admin adds to slang_dictionary or street dictionary are auto-removed from unrecognized list

**Output:** `location_type` (exact/street/area/district), `address`, `landmarks`, `confidence`

**Unresolved criteria:** confidence < 0.4 OR no location found by either method OR multiple conflicting locations

**4. Geocoder**
- Check geocode cache first (same street should not be geocoded repeatedly)
- Map old street names → new via `street_renames` table
- Sequential fallback chain:
  1. Geocode cache lookup
  2. Local Photon instance (primary, no rate limits)
  3. Nominatim public API (fallback, rate-limited queue — see below)
  4. District/landmark dictionary with fixed coordinates/polygons
- **Bounding box validation:** if geocoder result is outside city bbox:
  - Do NOT reject immediately — try next fallback in chain
  - If all fallbacks return out-of-bbox results → save best result with `out_of_bounds = true` and confidence penalty (× 0.3), route to admin review instead of silent discard
- If all fallbacks fail entirely (no result) → mark as unresolved with confidence 0.0
- Store successful results in `geocode_cache` (TTL: 90 days, refreshed on hit)

**Nominatim rate-limit queue:**
- In-memory queue with 1 req/sec rate limiter (token bucket)
- During normal operation: queue is near-empty (most queries resolved by cache + Photon)
- During bootstrap (cold cache): queue may grow — posts waiting for Nominatim are processed asynchronously, marked as `status = pending` until geocoded
- Queue overflow protection: if queue exceeds 500 items, remaining posts stay as `status = pending` and are retried on next pipeline cycle
- Metrics: log queue depth per cycle for monitoring

**Photon setup:**
- Open-source geocoder built on OSM data (komoot/photon)
- Import only Ukraine extract (~1-2 GB vs 100+ GB full planet)
- Runs as local Java service, REST API on `localhost:2322`
- API compatible with Nominatim response format → minimal code changes
- No rate limits — handles 100+ req/sec locally

**5. Data Normalizer**
- Determine geometry type based on data:
  - Exact address → Point
  - Street name (without building number) → Point (street centroid) + metadata `geo_type = street`
  - Street + landmark → Point (near landmark)
  - Area/district → Polygon (from `districts` table)
  - Multiple locations in one post → multiple Points
- **MVP simplification:** all locations except districts are stored as Points with metadata. Street LineString rendering deferred to post-MVP (requires OSM geometry integration).
- Assign final confidence level
- Track new slang candidates: if unknown term resolved to known location, save to `slang_dictionary` with `status = pending`
- Save to `locations` table
- Low confidence → mark post as `unresolved`

### Adaptive Precision

The system determines the best possible geocoding precision from available data:
- Full address (street + building number) → exact Point
- Street name + landmark → approximate Point (near landmark)
- Street name only → Point at street centroid + `geo_type = street` metadata
- District/neighborhood name → district Polygon
- Vague reference ("somewhere on Tairova") → district polygon with low confidence

**MVP geometry:** all locations stored as Points (except districts = Polygons). The `geo_type` metadata preserves the semantic meaning (exact/street/area/district) for future rendering upgrades. Post-MVP: street-level LineString via OSM geometry integration.

**Post-MVP preparation:** locations with `geo_type = street` or `area` store normalized `street_name` separately (see `locations` schema). This enables:
- Grouping multiple events on the same street for future LineString rendering
- Direct lookup against OSM street geometries without parsing free-text `address`
- Heatmap street-level aggregation: events on the same street contribute to one corridor intensity, not scattered points

### Confidence Scoring

Confidence is a weighted score (0.0–1.0) calculated as:

```
confidence = (extraction_score * 0.5) + (geocoder_score * 0.5)
```

- `extraction_score`:
  - Rule-based match: `rapidfuzz_score / 100` (e.g., 0.92 for 92% token match)
  - NER-only match: `spacy_confidence * 0.5` (penalty for unconfirmed NER)
  - Rule-based + NER agree: `max(rule_score, ner_score)` (mutual confirmation)
- `geocoder_score`: 1.0 if exact match, 0.7 if partial, 0.3 if only district-level, 0.0 if failed

Thresholds:
- >= 0.7 → auto-resolved (high confidence)
- 0.4–0.7 → auto-resolved but flagged for review
- < 0.4 → unresolved, sent to admin queue

### Heatmap Intensity

Intensity per location is calculated with time decay:

```
intensity = event_count * exp(-0.03 * hours_since_last_event)
```

- `event_count`: number of posts referencing this location in the selected date range
- `hours_since_last_event`: hours since the most recent post
- Decay rate 0.03 means: ~50% intensity after 24h, ~15% after 72h
- Backend aggregates into grid cells for performance

### Self-Learning Dictionary

- `slang_dictionary` table stores slang → resolved name mappings per city
- **No fully automatic learning.** All auto-detected mappings go through validation.

**Auto-learn workflow (pending queue):**
1. Analyzer extracts unknown term not in dictionary
2. Geocoder resolves it to a location
3. Entry is saved with `status = pending`, NOT active — it is not used for future processing yet
4. System tracks occurrences: each time the same `slang → location` pair is detected, `usage_count` increments
5. **Activation threshold:** entry becomes active (`status = active`) only when:
   - `usage_count >= 3` (same mapping confirmed by 3+ independent posts) AND geocoder resolved to the same location each time
   - OR admin manually approves via admin panel
6. Admin can review pending entries in `/admin/dictionary` — approve, edit, or reject
7. Active entries with no usage for 90 days → demoted back to `pending`
8. Admin-added entries (`auto_learned = false`) are always active, never auto-demoted

**slang_dictionary status flow:**
```
detected → pending (inactive, not used for matching)
              ↓ 3+ confirmations OR admin approval
           active (used for matching)
              ↓ 90 days no usage
           pending (demoted, needs re-confirmation)
              ↓ admin rejection
           rejected (permanently excluded)
```

- `usage_count` tracks how often the mapping was detected
- Higher usage_count entries are shown first in admin review queue

### Street Rename Handling

- `street_renames` table maps old street names to current official names per city
- Includes `year_renamed` for context
- Geocoder tries current name first, falls back to old name mapping if not found

---

## Database Schema

### posts

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL PK | |
| telegram_id | BIGINT UNIQUE | Telegram message ID, prevents duplicates |
| channel_id | BIGINT | Telegram channel ID |
| raw_text | TEXT | Original post text |
| cleaned_text | TEXT | Text after preprocessing |
| post_date | TIMESTAMPTZ | Original post date from Telegram |
| fetched_at | TIMESTAMPTZ | When the post was fetched |
| status | ENUM | pending, processed, failed, permanent_failure, unresolved |
| retry_count | INT DEFAULT 0 | Number of processing retries (max 3) |
| error_message | TEXT NULL | Last processing error details |
| is_deleted | BOOLEAN DEFAULT FALSE | Post was deleted in Telegram |
| city_id | FK → cities | |

### locations

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL PK | |
| post_id | FK → posts | One post can have multiple locations (1:N) |
| geometry | GEOMETRY (PostGIS) | MVP: Point (all) or Polygon (districts only) |
| geo_type | ENUM | point, street, area, district (semantic type, independent of geometry) |
| address | TEXT | Resolved address text (free-form) |
| street_name | VARCHAR NULL | Normalized street name for grouping (NULL for districts/landmarks) |
| confidence | FLOAT | 0.0–1.0, how certain the system is |
| out_of_bounds | BOOLEAN DEFAULT FALSE | Geocoder result was outside city bounding box |
| resolved | BOOLEAN | Whether location was confirmed |
| resolved_by | ENUM | auto, manual |
| created_at | TIMESTAMPTZ | |

### cities

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL PK | |
| name | VARCHAR | City name (Ukrainian) |
| name_ru | VARCHAR | City name (Russian) |
| bbox_north | FLOAT | Bounding box for geocoder validation |
| bbox_south | FLOAT | |
| bbox_east | FLOAT | |
| bbox_west | FLOAT | |
| default_zoom | INT | Default map zoom level |

### slang_dictionary

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL PK | |
| city_id | FK → cities | |
| slang | VARCHAR | Slang term or abbreviation |
| resolved_name | VARCHAR | Full official name |
| entity_type | ENUM | street, district, landmark |
| status | ENUM | pending, active, rejected |
| usage_count | INT | Times this mapping was detected |
| auto_learned | BOOLEAN | Learned automatically vs manually added |
| last_used_at | TIMESTAMPTZ | For 90-day demotion tracking |

### street_renames

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL PK | |
| city_id | FK → cities | |
| old_name | VARCHAR | Previous street name |
| new_name | VARCHAR | Current official name |
| year_renamed | INT | Year of renaming |

### channel_state

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL PK | |
| city_id | FK → cities | |
| channel_id | BIGINT | Telegram channel ID |
| last_message_id | BIGINT | Last fetched message ID for incremental sync |
| updated_at | TIMESTAMPTZ | When last_message_id was updated |

### geocode_cache

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL PK | |
| city_id | FK → cities | |
| query | VARCHAR | Geocoding query string |
| result_lat | FLOAT | |
| result_lng | FLOAT | |
| result_type | VARCHAR | Nominatim result type |
| created_at | TIMESTAMPTZ | |
| hit_count | INT | Number of cache hits |

### districts

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL PK | |
| city_id | FK → cities | |
| name | VARCHAR | District name (Ukrainian) |
| name_ru | VARCHAR | District name (Russian) |
| polygon | GEOMETRY(POLYGON) | District boundary |

### unrecognized_tokens

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL PK | |
| city_id | FK → cities | |
| token | VARCHAR | Unrecognized token or n-gram |
| occurrence_count | INT DEFAULT 1 | How many posts contained this token |
| sample_post_ids | BIGINT[] | Up to 5 post IDs for admin context |
| first_seen_at | TIMESTAMPTZ | |
| last_seen_at | TIMESTAMPTZ | |

### worker_heartbeat

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL PK | |
| heartbeat_at | TIMESTAMPTZ | Last heartbeat timestamp |
| status | VARCHAR | idle, running, error |
| current_job | VARCHAR NULL | Description of current activity |
| posts_processed | INT | Posts processed in current/last cycle |

---

## API Endpoints

### Public API

**`GET /api/locations`** — Main map endpoint. Returns geolocations within the visible map area as GeoJSON FeatureCollection. **Mandatory `bbox` parameter** limits results to current viewport — never returns all data at once.

Parameters: `bbox` (required, `south,west,north,east`), `date_from`, `date_to`, `geo_type` (comma-separated), `min_confidence`, `city_id`, `limit` (default 500, max 2000), `offset`

Frontend calls this endpoint on every map pan/zoom with current viewport bbox. PostGIS `ST_Within` handles spatial filtering efficiently (requires spatial index on `geometry` column).

**`GET /api/heatmap`** — Lightweight heatmap data endpoint. Returns **aggregated grid cells**, not raw points. Server groups locations into grid cells (configurable resolution, default ~100m) and returns `[lat, lng, intensity]` per cell. Intensity calculated using time-decay formula (see Heatmap Intensity section). Grid resolution adapts to zoom level.

Parameters: `bbox` (required), `date_from`, `date_to`, `city_id`, `zoom` (determines grid resolution)

**`GET /api/route/check`** — Route safety check. Accepts A and B coordinates, builds route via OSRM, then checks proximity to dangerous locations using PostGIS `ST_DWithin(route, location, buffer)`. Buffer = configurable radius in meters (default 50m) — catches Points near the route without requiring exact intersection. For district Polygons uses `ST_Intersects`. `relevance_hours` filters only recent events.

Parameters: `from_lat`, `from_lng`, `to_lat`, `to_lng`, `relevance_hours`, `city_id`, `buffer_meters` (optional, default 50)

Response:
```json
{
  "route": "GeoJSON LineString",
  "warnings": [
    {
      "location": { "lat": 46.47, "lng": 30.73, "address": "вул. Генуезька", "geo_type": "street" },
      "events_count": 3,
      "last_event": "2026-03-22T12:00:00Z",
      "confidence": 0.85
    }
  ],
  "safe": false
}
```

**`GET /api/stats`** — Sidebar statistics. Returns counts of points, streets, districts, and unresolved posts for current filter selection. Lightweight COUNT query to DB.

Parameters: `date_from`, `date_to`, `city_id`

**`GET /api/cities`** — List of available cities. For MVP returns only Odesa, but endpoint is ready for extension. Frontend uses for city selector dropdown.

### API Performance

- **In-memory response cache:** `/api/locations`, `/api/heatmap`, `/api/stats` cached by full query string (bbox + filters). Cache invalidated when worker completes a pipeline cycle (writes `last_pipeline_completed_at` to DB; API checks on each request, or via TTL = 10 minutes as simpler alternative). Same bbox+filters within one pipeline cycle → instant response from cache.
- **Rate limiting:** `slowapi` (FastAPI middleware), 60 req/min per IP for public endpoints, 120 req/min for admin. Prevents accidental loops and scripted abuse. Returns `429 Too Many Requests` with `Retry-After` header.

### Admin API (JWT-protected)

**`POST /api/auth/login`** — Admin authentication. Simple username/password, returns JWT access token. MVP: single admin account.

Request: `{ username, password }`
Response: `{ access_token }`

**`GET /api/admin/unresolved`** — Paginated list of unresolved posts with details: raw text, suggested location (if any), post date. For admin review interface.

Parameters: `page`, `limit`, `sort`

**`POST /api/admin/unresolved/{id}/confirm`** — Confirm system-suggested location. Post status changes from `unresolved` → `processed`. Slang dictionary and geocode cache updated if applicable.

**`POST /api/admin/unresolved/{id}/edit`** — Manually correct location. Admin provides correct coordinates, geo_type, and address. Side effects: (1) creates/updates geocode_cache entry, (2) if post contained unknown slang that maps to this location, creates slang_dictionary entry with confidence 1.0, (3) overrides any previous auto-learned entry for same term.

Request: `{ location: { lat, lng, geo_type, address }, slang_term?: string }`

**`POST /api/admin/unresolved/{id}/reject`** — Mark post as not containing useful location data. Post is excluded from map display.

**`GET /api/admin/dictionary`** — Paginated list of slang dictionary entries. Filterable by status (pending/active/rejected). Pending entries sorted by usage_count descending (most common first).

Parameters: `status`, `page`, `limit`, `city_id`

**`POST /api/admin/dictionary/{id}/approve`** — Approve pending slang entry. Sets status to active. Entry immediately starts being used in text analysis.

**`POST /api/admin/dictionary/{id}/edit`** — Edit slang entry mapping. Admin can correct the resolved_name.

Request: `{ resolved_name, entity_type }`

**`POST /api/admin/dictionary/{id}/reject`** — Permanently reject a slang entry. Term will be ignored in future auto-detection.

**`GET /api/admin/unrecognized-tokens`** — Top unrecognized tokens sorted by `occurrence_count` descending. Each entry includes sample post excerpts (from `sample_post_ids`) for context. Admin can: add to slang_dictionary (creates entry with `status = active`), dismiss (removes from list), or ignore.

Parameters: `page`, `limit`, `city_id`

**`POST /api/admin/unrecognized-tokens/{id}/add-to-dictionary`** — Convert unrecognized token to slang_dictionary entry. Admin provides `resolved_name` and `entity_type`. Entry created as `status = active`, `auto_learned = false`. Token removed from unrecognized list.

Request: `{ resolved_name, entity_type }`

**`POST /api/admin/unrecognized-tokens/{id}/dismiss`** — Dismiss token from unrecognized list (not a location term). Token is soft-deleted, won't reappear.

**`GET /api/admin/stats`** — Processing statistics: total posts, processed, unresolved, rejected counts. Includes dictionary stats: pending entries count, active entries count. Includes unrecognized tokens count for attention indicator.

**`POST /api/admin/pipeline/trigger`** — Manual pipeline trigger for development and debugging. Runs processing cycle immediately instead of waiting for hourly scheduler.

**`GET /api/admin/worker/status`** — Worker health status. Reads `worker_heartbeat` table, returns state (`alive`/`stale`/`dead`), last heartbeat time, current job info, posts processed in last cycle.

**`POST /api/admin/posts/{id}/retry`** — Re-queue a failed/permanent_failure post for reprocessing. Resets `status = pending`, `retry_count = 0`. Useful when pipeline bug was fixed and old failures need reprocessing.

---

## Frontend

### Visual Style

**Swiss Minimal** — sans-serif typography (system font stack), pure white background, strong typographic hierarchy, strict grid layout. Clean, magazine-like aesthetic inspired by Vogue/Kinfolk.

- Color palette: white (#FFFFFF) background, near-black (#111) text, light gray (#F5F5F5) secondary surfaces, subtle borders (#EEE)
- Danger indicators: muted red for heatmap/warnings, not aggressive
- Typography: system sans-serif, uppercase labels with letter-spacing, light font-weight for secondary text
- Minimal UI chrome: no shadows, thin borders, generous whitespace

### Layout

- **Collapsible sidebar** (left) — hamburger toggle, collapses to icon-only strip, map expands to full width
- **Full-screen Leaflet map** (main area) — OSM light/neutral tile layer

### Sidebar Controls

- **Date Range** — date picker + quick buttons (Today / Week / Month / All)
- **Display Mode** — Heatmap / Points & Streets / Districts (radio toggle)
- **Confidence slider** — minimum confidence threshold for displayed data
- **Route Check** — input fields for points A and B, relevance hours selector, "Check Route" button
- **Stats** — live counts for current filter selection (points, streets, districts, unresolved)

### Map Features

- **Leaflet.markercluster** — zoom-based clustering. At low zoom: clusters as circles with count numbers. At high zoom: individual points and district polygons
- **leaflet.heat** — heatmap layer, intensity adapts to zoom level
- **OSRM routing** — route polyline with intersection warnings
- **Popup on click** — address, date, post excerpt, confidence score, geo_type badge
- **Route warnings** — highlighted intersection points with danger zone details

### Frontend Performance

- **Debounce on filters:** all filter changes (date, mode, confidence slider) debounced 300ms before triggering API call. Prevents request spam during slider drag or rapid clicks.
- **Debounce on map move:** `moveend` event debounced 500ms before fetching new bbox data. Prevents flooding API during pan/zoom.
- **Lazy loading by zoom:** at low zoom (< 12) show only heatmap or clusters, skip loading individual points. Individual points fetched only at zoom >= 14.
- **Server-side clustering:** at zoom < 14, `/api/locations` returns pre-clustered data (PostGIS `ST_ClusterDBSCAN` or grid-based grouping) with cluster center + count. Frontend renders clusters directly without client-side computation. At zoom >= 14, returns individual points for `Leaflet.markercluster` fine-grained rendering.
- **Cancel in-flight requests:** new filter/bbox change cancels previous pending HTTP request (RxJS `switchMap`).
- **Lightweight responses:** heatmap endpoint returns aggregated grid, not raw points. Locations endpoint returns only fields needed for rendering (no raw_text in map response, only in popup on-demand).

### Data Refresh

- Frontend polls `/api/stats` every 5 minutes to detect new data
- If stats changed → re-fetch current view data (`/api/locations` or `/api/heatmap`)
- No WebSocket for MVP — simple polling is sufficient for hourly-updated data

### Pages

- `/` — Main map view (public, no auth)
- `/admin` — Dashboard: action-oriented counters (needs attention / pending review / system health / today's stats), auth-protected
- `/admin/unresolved` — Unresolved posts table, mini-map per post for manual resolution, auth-protected
- `/admin/dictionary` — Slang dictionary management: pending queue, active entries, rejected entries, auth-protected

### Angular Components

- `MapComponent` — Leaflet map with layer management
- `FilterPanelComponent` — sidebar with all filters, collapsible
- `StatsComponent` — statistics display
- `RouteCheckComponent` — route input and results
- `AdminDashboardComponent` — action-oriented overview: attention counters, system health, today's stats
- `AdminUnresolvedComponent` — table of unresolved posts with resolution tools
- `AdminDictionaryComponent` — slang dictionary management: pending review queue, approve/edit/reject
- `FilterService` — shared state for filters, emits changes to map
- `ApiService` — HTTP client for backend communication
- `AuthService` — JWT token management for admin

---

## Potential Challenges & Solutions

### Fuzzy Locations ("somewhere on Tairova")

- Maintain dictionary of districts/microdistricts with polygons
- Known landmarks → fixed coordinates (Privoz, Arcadia, 7th km market)
- Store **precision level** (exact/street/area/district) per location
- Display accordingly: point, line, radius, polygon

### Slang & Abbreviations

- Self-learning dictionary updated from confirmed geocodings
- Each entry has confidence score based on successful usage history
- Fuzzy matching via `rapidfuzz` for typos
- Per-city configuration (JSON-based dictionaries)

### Geocoding Errors

- City bounding box — reject results outside city limits
- Confidence scoring — below threshold → unresolved queue
- Geocode caching — same street geocoded once
- Fallback chain: cache → local Photon → Nominatim → district dictionary
- Local Photon eliminates rate-limit bottleneck for high-volume processing

### Street Renames

- `street_renames` table with old→new mapping per city
- Geocoder applies mapping before querying Nominatim
- Both old and new names stored for search

### Multiple Locations in One Post

- One post can reference multiple locations (1:N relationship)
- MVP: each location stored as separate Point
- Heatmap layer naturally aggregates nearby points into intensity zones
- Post-MVP: detect street segments and render as LineString

---

## Scheduling & Worker

**MVP:** Pipeline runs as a **separate Python process** (not inside FastAPI).

```
┌─────────────────┐       ┌─────────────────┐
│  FastAPI (API)   │       │  Worker process  │
│  serves frontend │       │  APScheduler     │
│  + admin panel   │       │  + pipeline      │
│                  │       │                  │
│  port 8000       │       │  no port         │
└────────┬─────────┘       └────────┬─────────┘
         │                          │
         └──────────┬───────────────┘
                    ▼
            PostgreSQL + PostGIS
```

- **Two processes, shared DB:** FastAPI reads data, Worker writes data. No in-process coupling.
- **Worker:** standalone Python script with APScheduler, runs pipeline on hourly interval
- **Benefits:** API server stays responsive, pipeline crash doesn't kill API, independent restart/scaling
- **Launch:** `python -m app.api` (API) + `python -m app.worker` (pipeline). Both in one `docker-compose.yml` for convenience.
- **Concurrency lock:** DB-based advisory lock (`pg_try_advisory_lock`) instead of file-based lock. Benefits: auto-released on process crash (connection closes → lock released), no stale lock files, no PID cleanup logic. Job timeout: 50 minutes — if exceeded, connection is killed and lock auto-releases.
- **Batch processing:** posts processed in batches of 100 to manage memory. Each batch wrapped in a transaction with **savepoint per post** — individual post failure rolls back only that savepoint, rest of batch commits normally. Each batch commits to DB before starting the next.
- **Failure handling:** individual post failures don't stop the batch. Failed posts marked as `status=failed` with error details stored in `error_message` field. Retry on next cycle (max 3 retries tracked via `retry_count`, then `status=permanent_failure`). Admin can manually re-queue permanent failures via `POST /api/admin/posts/{id}/retry`.
- **Worker health monitoring:**
  - Worker writes heartbeat to `worker_heartbeat` DB table every 60 seconds (timestamp + current job status)
  - `GET /api/admin/worker/status` — API reads heartbeat table, returns worker state: `alive` (heartbeat < 2 min ago), `stale` (2–10 min), `dead` (> 10 min)
  - Admin panel shows worker status indicator (green/yellow/red)
  - No external monitoring tools for MVP — DB heartbeat is simple and sufficient
- **Manual trigger:** `POST /api/admin/pipeline/trigger` sends signal to worker via DB flag (worker checks on next tick).
- **Post-MVP:** replace APScheduler with Celery + Redis, worker becomes Celery worker. Minimal code changes due to separation.

---

## AI Provider (Future Upgrade)

Text analysis provider is abstracted behind an interface. MVP uses spaCy + rule-based system (free). When ready to invest:
- Gemini Flash (cheapest cloud option)
- OpenAI GPT-4o-mini
- Claude Haiku
- Local model via Ollama

Switch requires only configuration change, no pipeline modifications.

---

## Operational Risks & Mitigations

### Scalability Thresholds

Current architecture (APScheduler + single worker) handles up to ~50k posts/day comfortably. Migration triggers:

| Signal | Threshold | Action |
|--------|-----------|--------|
| Pipeline cycle duration | > 30 min consistently | Optimize bottleneck (likely geocoding) |
| Pipeline cycle duration | > 45 min consistently | Migrate to Celery + Redis |
| Number of channels | > 5 | Celery with per-channel task queue |
| Nominatim queue depth | > 200 per cycle consistently | Deploy own Nominatim instance |

Worker logs pipeline duration and queue depth per cycle. Admin stats endpoint includes these metrics for monitoring.

### External Service Degradation

Both Nominatim and OSRM are public APIs without SLA. Graceful degradation strategy:

**Nominatim unavailable:**
- Geocode cache + local Photon cover >95% of queries — Nominatim outage has minimal impact
- If Nominatim returns errors/timeouts (3 consecutive failures) → skip Nominatim for remainder of cycle, fall through to district dictionary
- Posts that needed Nominatim stay as `status = pending`, retried next cycle
- Log warning with failure count per cycle

**OSRM unavailable:**
- Route check is a user-facing feature, not pipeline-critical
- If OSRM returns error/timeout (5 sec) → return `{ "error": "routing_unavailable", "message": "..." }` with HTTP 503
- Frontend shows user-friendly message: "Route check temporarily unavailable, try again later"
- No retry/queue — user retries manually

### Admin Dashboard Clarity

Admin panel organizes statuses into **action-oriented sections**, not raw status lists:

**Dashboard home (`/admin`):**
- **Needs attention** (red count): unresolved posts + permanent_failure posts + high-frequency unrecognized tokens (occurrence_count ≥ 10)
- **Pending review** (yellow count): pending slang entries + flagged locations (confidence 0.4–0.7) + out_of_bounds locations
- **System health** (green/yellow/red): worker status, last pipeline time, Nominatim availability
- **Processed today** (info): posts processed, locations created, cache hit rate

Each counter is a clickable link to the filtered list. Admin sees what needs action without understanding internal status enums.
