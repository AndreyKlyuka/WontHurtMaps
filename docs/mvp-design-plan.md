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

| Layer           | Technology                                                                               |
| --------------- | ---------------------------------------------------------------------------------------- |
| Frontend        | Angular + Leaflet (OSM tiles)                                                            |
| Backend / API   | Python, FastAPI                                                                          |
| Telegram client | Telethon (MTProto)                                                                       |
| Text analysis   | LLM API (Gemini free tier) for structured address extraction; Pydantic output validation |
| Geocoding       | Google Maps Geocoding API + geocode cache (DB-based, 90-day TTL)                         |
| Routing         | OSRM (free)                                                                              |
| Database        | PostgreSQL + PostGIS                                                                     |
| Scheduler       | APScheduler (MVP), migration-ready for Celery + Redis                                    |
| Auth            | JWT (simple admin auth for MVP)                                                          |

### System Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        ANGULAR FRONTEND                         │
│  ┌──────────┐  ┌──────────────┐  ┌────────────┐  ┌──────────┐   │
│  │  Leaflet │  │  Heatmap     │  │  Date/Mode │  │  Admin   │   │
│  │  Map     │  │  Layer       │  │  Filters   │  │  Panel   │   │
│  └──────────┘  └──────────────┘  └────────────┘  └──────────┘   │
└────────────────────────┬────────────────────────────────────────┘
                         │ REST API (JSON / GeoJSON)
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                     PYTHON BACKEND (FastAPI)                    │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────┐ │
│  │  Public API  │  │  Scheduler   │  │  Processing Pipeline   │ │
│  │  /api/*      │  │  (hourly)    │  │                        │ │
│  │              │  │              │  │  1. Telegram Fetcher   │ │
│  │  Admin API   │  │  Triggers    │  │  2. Text Preprocessor  │ │
│  │  /api/admin/*│──│─ pipeline ──▶│  │  3. NLP Analyzer       │ │
│  │  (JWT auth)  │  └──────────────┘  │  4. Geocoder           │ │
│  └──────────────┘                    │  5. Data Normalizer    │ │
│                                      └────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                    Service Layer                           │ │
│  │  ┌─────────────┐ ┌──────────────┐ ┌──────────────────────┐ │ │
│  │  │ SlangDict   │ │ StreetRename │ │ ConfidenceScorer     │ │ │
│  │  │ Service     │ │ Service      │ │ Service              │ │ │
│  │  │ (self-learn)│ │ (old→new)    │ │ (exact/street/area)  │ │ │
│  │  └─────────────┘ └──────────────┘ └──────────────────────┘ │ │
│  └────────────────────────────────────────────────────────────┘ │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                  POSTGRESQL + PostGIS                           │
│  ┌──────────┐ ┌───────────┐ ┌──────────┐ ┌──────────────────┐   │
│  │ posts    │ │ locations │ │ slang_   │ │ street_renames   │   │
│  │ (raw)    │ │ (geo)     │ │ dict     │ │ (old → new)      │   │
│  └──────────┘ └───────────┘ └──────────┘ └──────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Processing Pipeline

When the system is active, it processes posts from the last hour on an hourly cycle.

### Pipeline Stages

**1. Telegram Fetcher**

- Telethon MTProto client with dedicated account
- Session persistence: Telethon session file stored on disk (`.session` file), auto-reloads on restart
- **Channel identification:** channel identified by its **display title** (the name shown in the channel header). Configured via the admin panel (production) or `TELEGRAM_CHANNEL_NAME` env variable (dev override). MVP uses a hardcoded fallback name until the admin panel is implemented.
- **Channel resolution:** on first run, the worker iterates account dialogs (`iter_dialogs()`) to find the channel by title match (case-insensitive). Works for both public and private channels the account is a member of. Once found, the numeric `channel_id` is stored in the `channel_state` DB table and reused on all subsequent pipeline cycles (fast path).
- **Incremental fetching:** tracks `last_message_id` per channel (stored in DB). Each cycle fetches from `last_message_id + 1` to newest. Never relies on time-based "last hour" — prevents gaps and duplicates after downtime.
- On first run (no `last_message_id`): fetches last N messages (configurable, default 500) to bootstrap
- After successful batch: updates `last_message_id` to highest fetched ID
- Saves raw post to `posts` table with status `pending`
- Deduplication by `telegram_id` as safety net (incremental fetch should prevent duplicates)
- **Deleted post tracking:**
  - Each pipeline cycle: worker queries DB for up to 500 stored post IDs (ordered newest-first), then verifies them via Telethon's `get_messages(ids=[...])` in batches of 100
  - IDs that return `None` from Telegram are soft-deleted: `is_deleted = true` in DB; all post data (including `raw_text`) is preserved
  - Deleted posts are excluded from the public map (`GET /api/locations` filters `is_deleted = false`)
  - Admin can view deleted posts at `GET /api/admin/posts/deleted` with full `raw_text`, `cleaned_text`, and location records — useful for auditing complex address extractions that were lost when the post was removed
- **Telegram rate limit handling:**
  - `FloodWaitError` → respect Telegram's wait time, log warning, resume after delay
  - Fetch in small batches (100 messages per request) to avoid hitting limits
  - Exponential backoff on network errors (3 attempts)
  - Auth errors → log and alert, skip cycle

**2. Text Preprocessor**

- Remove emoji, formatting artifacts
- Normalize Unicode (е/ё, і/i)
- Clean text stored as `cleaned_text`

> Slang replacement is intentionally omitted: the LLM handles colloquial names and mixed Ukrainian/Russian text via prompt context and dynamic few-shot examples (see section 3).

**3. Location Analyzer (LLM-based)**

Extracts addresses, intersections, and directional references from post text using an LLM API (Gemini free tier). The LLM understands natural language patterns that rule-based systems struggle with: street intersections, directions along streets, approximate landmarks, and mixed Ukrainian/Russian text.

**Input:** `cleaned_text` from preprocessor + city context (name, city hint)

**LLM request:**

- Single API call per post with a structured prompt
- Prompt instructs the model to extract: exact addresses, street intersections, directional references, district/area names
- City context passed in the system prompt to guide disambiguation
- **Dynamic few-shot examples:** 3 real verified posts from the same channel are attached to each prompt (see Few-Shot Pool below)

**Expected structured output (JSON):**

```json
{
  "locations": [
    {
      "type": "address",
      "value": "вул. Дерибасівська, 5",
      "confidence": 0.95
    },
    {
      "type": "intersection",
      "value": "Дерибасівська / Рішельєвська",
      "confidence": 0.88
    },
    {
      "type": "direction",
      "value": "вздовж Фонтанської від Люстдорфської",
      "confidence": 0.75
    },
    {
      "type": "district",
      "value": "Таїрова",
      "confidence": 0.9
    }
  ]
}
```

**Output validation:**

- LLM response parsed and validated via Pydantic model
- Invalid or malformed JSON → retry once → mark post as `unresolved` if still fails
- Empty `locations` array → mark as `unresolved`, log for admin review

**Rate limiting (Gemini free tier):**

- 15 RPM limit respected via in-process token bucket (same pattern as geocoder queue)
- Queue overflow protection: if queue exceeds 500 items, remaining posts stay `status = pending` until next cycle

**Fallback on API failure:**

- LLM API unavailable or returns error → mark post as `failed`, `retry_count++`
- 3 consecutive LLM failures → skip LLM for remainder of cycle, all pending posts stay `status = pending`

**Unrecognized address logging:**

- If LLM returns locations but Geocoder cannot resolve any of them → save unresolved address strings to `unrecognized_tokens` table
- Each unique address tracked with `occurrence_count` — helps admin identify frequently mentioned locations that need manual geocoding or dictionary additions
- Admin panel shows top unresolved addresses sorted by frequency

**Output:** `location_type` (address/intersection/direction/district), `address`, `confidence`

**Unresolved criteria:** LLM returns empty locations OR Pydantic validation fails OR all extracted locations fail geocoding

**Few-Shot Pool:**

The prompt includes 3 real examples drawn once per pipeline cycle (all posts in a batch share the same 3 examples). An example is eligible when:

- `confidence >= 0.95` (LLM + geocoder combined score) AND
- `admin_verified = true` (admin explicitly confirmed the location)

After admin verification, confidence is treated as 1.0 regardless of the original score.

**Bootstrap fallback:** if the verified pool has fewer than 3 entries, static hardcoded examples from real Odesa posts are used instead.

```sql
SELECT l.*, p.raw_text FROM locations l
JOIN posts p ON p.id = l.post_id
WHERE l.confidence >= 0.95 AND l.admin_verified = true
ORDER BY RANDOM() LIMIT 3
```

**4. Geocoder**

- Check geocode cache first (same street should not be geocoded repeatedly)
- Map old street names → new via `street_renames` table (only active renames)
- Sequential fallback chain:
  1. Geocode cache lookup
  2. Google Maps Geocoding API
  3. District dictionary with fixed coordinates/polygons
- **Bounding box validation:** if geocoder result is outside city bbox:
  - Do NOT reject immediately — try next fallback in chain
  - If all fallbacks return out-of-bbox results → save best result with `out_of_bounds = true` and confidence penalty (× 0.3), route to admin review instead of silent discard
- If all fallbacks fail entirely (no result) → mark as unresolved with confidence 0.0
- Store successful results in `geocode_cache` (TTL: 90 days, refreshed on hit)

**Google Maps Geocoding API:**

- No strict per-second rate limit (up to 50 QPS); queue kept for overflow protection only
- Queue overflow protection: if queue exceeds 500 items, remaining posts stay `status = pending` and are retried on next cycle
- Metrics: log queue depth per cycle for monitoring
- 3 consecutive API failures → skip for remainder of cycle
- Billing: $200/month free credit (~40k requests); with 90-day cache hit rate ~80%, expected volume well within free tier
- API key configured via `GOOGLE_MAPS_API_KEY` env var (Google Maps Platform — separate from Gemini key)

**5. Data Normalizer**

- Determine geometry type based on data:
  - Exact address → Point
  - Street name (without building number) → Point (street centroid) + metadata `geo_type = street`
  - Street + landmark → Point (near landmark)
  - Area/district → Polygon (from `districts` table)
  - Multiple locations in one post → multiple Points
- **MVP simplification:** all locations except districts are stored as Points with metadata. Street LineString rendering deferred to post-MVP (requires OSM geometry integration).
- Assign final confidence level
- Set `admin_verified = false` by default on all new locations (admin verifies via admin panel)
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
  - LLM-reported confidence for the extracted location (0.0–1.0 from structured output)
  - If LLM returns no confidence → use 0.5 as default for present extractions
- `geocoder_score`: 1.0 if exact match, 0.7 if partial, 0.3 if only district-level, 0.0 if failed

Thresholds:

- > = 0.7 → auto-resolved (high confidence)
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

### Few-Shot Learning (replaces Self-Learning Dictionary)

The system improves LLM accuracy over time not through a slang dictionary but through a growing pool of verified real examples from the channel.

**How it grows:**

1. LLM extracts locations with confidence score (0.0–1.0)
2. Admin reviews flagged or low-confidence locations in the admin panel
3. On admin confirmation → `admin_verified = true` is set on the `Location` record
4. Verified locations with `confidence >= 0.95` enter the few-shot pool automatically

**Effect:** each pipeline cycle, 3 random examples from the pool are attached to the LLM prompt. The LLM sees real posts from this channel with confirmed correct extractions, which progressively improves its accuracy for local address patterns, landmarks, and mixed-language text.

**Slang dictionary role (read-only reference):**

`slang_dictionary` is retained as an admin-visible reference table only — it is NOT used during pipeline processing. Admins can add notes about known local terms; the table may inform future prompt engineering or static example selection. No automatic pipeline interaction.

### Street Rename Handling

- `street_renames` table maps old street names to current official names per city
- Includes `year_renamed` for context
- Geocoder tries current name first, falls back to old name mapping if not found

---

## Database Schema

### posts

| Column        | Type                  | Description                                                                                                |
| ------------- | --------------------- | ---------------------------------------------------------------------------------------------------------- |
| id            | SERIAL PK             |                                                                                                            |
| telegram_id   | BIGINT UNIQUE         | Telegram message ID, prevents duplicates                                                                   |
| channel_id    | BIGINT                | Telegram channel ID                                                                                        |
| raw_text      | TEXT                  | Original post text from Telegram — preserved permanently even after deletion for manual address validation |
| cleaned_text  | TEXT                  | Text after preprocessing (emoji removed, Unicode normalized) — sent to LLM                                 |
| post_date     | TIMESTAMPTZ           | Original post date from Telegram                                                                           |
| fetched_at    | TIMESTAMPTZ           | When the post was fetched                                                                                  |
| status        | ENUM                  | pending, processed, failed, permanent_failure, unresolved                                                  |
| retry_count   | INT DEFAULT 0         | Number of processing retries (max 3)                                                                       |
| error_message | TEXT NULL             | Last processing error details                                                                              |
| is_deleted    | BOOLEAN DEFAULT FALSE | Post was deleted in Telegram                                                                               |
| city_id       | FK → cities           |                                                                                                            |

### locations

| Column         | Type                  | Description                                                            |
| -------------- | --------------------- | ---------------------------------------------------------------------- |
| id             | SERIAL PK             |                                                                        |
| post_id        | FK → posts            | One post can have multiple locations (1:N)                             |
| geometry       | GEOMETRY (PostGIS)    | MVP: Point (all) or Polygon (districts only)                           |
| geo_type       | ENUM                  | point, street, area, district (semantic type, independent of geometry) |
| address        | TEXT                  | Resolved address text (free-form)                                      |
| street_name    | VARCHAR NULL          | Normalized street name for grouping (NULL for districts/landmarks)     |
| confidence     | FLOAT                 | 0.0–1.0, how certain the system is                                     |
| out_of_bounds  | BOOLEAN DEFAULT FALSE | Geocoder result was outside city bounding box                          |
| resolved       | BOOLEAN               | Whether location was confirmed                                         |
| resolved_by    | ENUM                  | auto, manual                                                           |
| admin_verified | BOOLEAN DEFAULT FALSE | Admin explicitly confirmed this location — qualifies for few-shot pool |
| created_at     | TIMESTAMPTZ           |                                                                        |

### cities

| Column       | Type      | Description                          |
| ------------ | --------- | ------------------------------------ |
| id           | SERIAL PK |                                      |
| name         | VARCHAR   | City name (Ukrainian)                |
| name_ru      | VARCHAR   | City name (Russian)                  |
| bbox_north   | FLOAT     | Bounding box for geocoder validation |
| bbox_south   | FLOAT     |                                      |
| bbox_east    | FLOAT     |                                      |
| bbox_west    | FLOAT     |                                      |
| default_zoom | INT       | Default map zoom level               |

### slang_dictionary

| Column        | Type        | Description                             |
| ------------- | ----------- | --------------------------------------- |
| id            | SERIAL PK   |                                         |
| city_id       | FK → cities |                                         |
| slang         | VARCHAR     | Slang term or abbreviation              |
| resolved_name | VARCHAR     | Full official name                      |
| entity_type   | ENUM        | street, district, landmark              |
| status        | ENUM        | pending, active, rejected               |
| usage_count   | INT         | Times this mapping was detected         |
| auto_learned  | BOOLEAN     | Learned automatically vs manually added |
| last_used_at  | TIMESTAMPTZ | For 90-day demotion tracking            |

### street_renames

| Column       | Type        | Description                                                               |
| ------------ | ----------- | ------------------------------------------------------------------------- |
| id           | SERIAL PK   |                                                                           |
| city_id      | FK → cities |                                                                           |
| old_name_uk  | VARCHAR     | Previous street name (Ukrainian)                                          |
| old_name_ru  | VARCHAR     | Previous street name (Russian)                                            |
| new_name_uk  | VARCHAR     | Current official name (Ukrainian)                                         |
| new_name_ru  | VARCHAR     | Current official name (Russian)                                           |
| year_renamed | INT         | Year of renaming                                                          |
| status       | ENUM        | pending, active, rejected — admin validates before system uses the rename |

### channel_state

| Column          | Type                 | Description                                          |
| --------------- | -------------------- | ---------------------------------------------------- |
| id              | SERIAL PK            |                                                      |
| city_id         | FK → cities          |                                                      |
| channel_id      | BIGINT               | Telegram channel numeric ID (resolved from link)     |
| channel_link    | VARCHAR NULL         | Original link as entered by admin (t.me or web link) |
| channel_title   | VARCHAR NULL         | Channel title (fetched via Telethon on add)          |
| is_active       | BOOLEAN DEFAULT TRUE | Whether worker should fetch from this channel        |
| last_message_id | BIGINT               | Last fetched message ID for incremental sync         |
| created_at      | TIMESTAMPTZ          | When the channel was added                           |
| updated_at      | TIMESTAMPTZ          | When last_message_id was updated                     |

### geocode_cache

| Column      | Type        | Description            |
| ----------- | ----------- | ---------------------- |
| id          | SERIAL PK   |                        |
| city_id     | FK → cities |                        |
| query       | VARCHAR     | Geocoding query string |
| result_lat  | FLOAT       |                        |
| result_lng  | FLOAT       |                        |
| result_type | VARCHAR     | Geocoder result type   |
| created_at  | TIMESTAMPTZ |                        |
| hit_count   | INT         | Number of cache hits   |

### districts

| Column  | Type              | Description               |
| ------- | ----------------- | ------------------------- |
| id      | SERIAL PK         |                           |
| city_id | FK → cities       |                           |
| name    | VARCHAR           | District name (Ukrainian) |
| name_ru | VARCHAR           | District name (Russian)   |
| polygon | GEOMETRY(POLYGON) | District boundary         |

### unrecognized_tokens

| Column           | Type          | Description                         |
| ---------------- | ------------- | ----------------------------------- |
| id               | SERIAL PK     |                                     |
| city_id          | FK → cities   |                                     |
| token            | VARCHAR       | Unrecognized token or n-gram        |
| occurrence_count | INT DEFAULT 1 | How many posts contained this token |
| sample_post_ids  | BIGINT[]      | Up to 5 post IDs for admin context  |
| first_seen_at    | TIMESTAMPTZ   |                                     |
| last_seen_at     | TIMESTAMPTZ   |                                     |

### worker_heartbeat

| Column          | Type         | Description                           |
| --------------- | ------------ | ------------------------------------- |
| id              | SERIAL PK    |                                       |
| heartbeat_at    | TIMESTAMPTZ  | Last heartbeat timestamp              |
| status          | VARCHAR      | idle, running, error                  |
| current_job     | VARCHAR NULL | Description of current activity       |
| posts_processed | INT          | Posts processed in current/last cycle |

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
      "location": {
        "lat": 46.47,
        "lng": 30.73,
        "address": "вул. Генуезька",
        "geo_type": "street"
      },
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

**`POST /api/admin/unresolved/{id}/confirm`** — Confirm system-suggested location. Sets `admin_verified = true`, post status changes from `unresolved` → `processed`. Geocode cache updated if applicable.

**`POST /api/admin/unresolved/{id}/edit`** — Manually correct location. Admin provides correct coordinates, geo_type, and address. Side effects: (1) creates/updates geocode_cache entry, (2) sets `admin_verified = true` on the corrected location.

Request: `{ location: { lat, lng, geo_type, address } }`

**`POST /api/admin/unresolved/{id}/reject`** — Mark post as not containing useful location data. Post is excluded from map display.

**`GET /api/admin/dictionary`** — Paginated list of slang dictionary entries (read-only reference, not used in pipeline). Admins can annotate local terms for documentation purposes.

Parameters: `page`, `limit`, `city_id`

**`POST /api/admin/dictionary`** — Add a reference entry (admin-only, informational).

Request: `{ slang, resolved_name, entity_type }`

**`DELETE /api/admin/dictionary/{id}`** — Remove a reference entry.

**`GET /api/admin/unrecognized-tokens`** — Top addresses that LLM extracted but Google Maps could not geocode, sorted by `occurrence_count` descending. Each entry includes sample post excerpts for context. Admin can dismiss tokens that are not real addresses.

Parameters: `page`, `limit`, `city_id`

**`POST /api/admin/unrecognized-tokens/{id}/dismiss`** — Dismiss token from list. Token is soft-deleted, won't reappear.

**`POST /api/admin/unrecognized-tokens/{id}/dismiss`** — Dismiss token from unrecognized list (not a location term). Token is soft-deleted, won't reappear.

**`GET /api/admin/stats`** — Processing statistics: total posts, processed, unresolved, rejected counts. Includes dictionary stats: pending entries count, active entries count. Includes unrecognized tokens count for attention indicator.

**`POST /api/admin/pipeline/trigger`** — Manual pipeline trigger for development and debugging. Runs processing cycle immediately instead of waiting for hourly scheduler.

**`GET /api/admin/worker/status`** — Worker health status. Reads `worker_heartbeat` table, returns state (`alive`/`stale`/`dead`), last heartbeat time, current job info, posts processed in last cycle.

**`POST /api/admin/posts/{id}/retry`** — Re-queue a failed/permanent_failure post for reprocessing. Resets `status = pending`, `retry_count = 0`. Useful when pipeline bug was fixed and old failures need reprocessing.

**`GET /api/admin/channel`** — Current channel configuration. Returns channel_id, channel_link, channel_title, is_active, last_message_id, connection status.

**`POST /api/admin/channel`** — Add/update channel. Admin provides a Telegram link (t.me or web link). Backend resolves link → numeric channel_id via Telethon, verifies account has access, fetches channel title. Saves to `channel_state`. MVP: one channel only (upsert).

Request: `{ channel_link, city_id }`

**`POST /api/admin/channel/{id}/toggle`** — Enable/disable channel fetching. Sets `is_active` flag.

**`GET /api/admin/posts/deleted`** — Paginated list of posts that were deleted from Telegram. Each post includes `raw_text`, `cleaned_text`, `post_date`, `status`, and associated location records. Allows admin to audit what address information was contained in removed posts and validate complex extractions manually.

Parameters: `page`, `limit`

**`GET /api/admin/processing-log`** — Paginated feed of all processed posts with full decision chain: extraction method, matched street, rename applied, geocode result, confidence breakdown. Filterable by status, confidence range, date range.

Parameters: `page`, `limit`, `status`, `min_confidence`, `max_confidence`, `date_from`, `date_to`

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
- Fallback chain: cache → Google Maps Geocoding API → district dictionary
- Geocode cache eliminates most repeated queries after warmup (80%+ hit rate expected)

### Street Renames

- `street_renames` table with old→new mapping per city
- Geocoder applies mapping before querying Google Maps
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
┌──────────────────┐       ┌──────────────────┐
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
- **Launch:** `python -m app.api` (API) + `python -m app.worker` (pipeline) from `backend/`. Both in one `docker-compose.yml` for convenience.
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

Text analysis provider is abstracted behind an interface. MVP uses Gemini (Google AI Studio free tier). When ready to upgrade:

- Gemini Pro / Flash (paid tiers for higher RPM)
- OpenAI GPT-4o-mini
- Claude Haiku
- Local model via Ollama

Switch requires only configuration change, no pipeline modifications.

---

## Operational Risks & Mitigations

### Scalability Thresholds

Current architecture (APScheduler + single worker) handles up to ~50k posts/day comfortably. Migration triggers:

| Signal                  | Threshold                    | Action                                                      |
| ----------------------- | ---------------------------- | ----------------------------------------------------------- |
| Pipeline cycle duration | > 30 min consistently        | Optimize bottleneck (likely geocoding)                      |
| Pipeline cycle duration | > 45 min consistently        | Migrate to Celery + Redis                                   |
| Number of channels      | > 5                          | Celery with per-channel task queue                          |
| Geocoding queue depth   | > 200 per cycle consistently | Monitor Google Maps billing; consider local Photon instance |

Worker logs pipeline duration and queue depth per cycle. Admin stats endpoint includes these metrics for monitoring.

### External Service Degradation

Both Google Maps Geocoding API and OSRM are external APIs. Graceful degradation strategy:

**Google Maps Geocoding API unavailable:**

- Geocode cache covers 80%+ of queries after warmup — outage has limited impact
- If API returns errors/timeouts (3 consecutive failures) → skip for remainder of cycle, fall through to district dictionary
- Posts that needed geocoding stay as `status = pending`, retried next cycle
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
- **System health** (green/yellow/red): worker status, last pipeline time, Geocoding API availability
- **Processed today** (info): posts processed, locations created, cache hit rate

Each counter is a clickable link to the filtered list. Admin sees what needs action without understanding internal status enums.
