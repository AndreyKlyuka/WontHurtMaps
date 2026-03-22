# WontHurtMaps — Product Requirements Document (PRD)

## 1. Product Overview

**WontHurtMaps** is a city safety monitoring system that aggregates data from Telegram channels. It automatically parses messages, extracts addresses and geolocations using NLP analysis, and visualizes them on an interactive map with heatmaps, points, streets, and districts.

**MVP target city:** Odesa (architecturally parametrized for extension to other cities).

---

## 2. Problem Statement

City residents lack a convenient way to assess the safety of specific locations or routes in near real-time. Information about dangerous areas is scattered across Telegram channels as unstructured text. Manually monitoring hundreds of messages per day is unrealistic.

**Core problem:** the gap between information availability (Telegram channels with thousands of daily posts) and its accessibility in a usable format for decision-making.

---

## 3. Target Users

### 3.1 Primary: City Residents (Public User)
- Want to check the safety of a specific location or route
- Need a quick overview of dangerous zones on a map
- No authentication required

### 3.2 Secondary: System Administrator (Admin)
- Manages data quality: resolves unrecognized posts, moderates dictionary
- Monitors system health: worker status, pipeline metrics
- Single admin account for MVP

---

## 4. User Stories

### Public User

| ID | Story | Acceptance Criteria |
|----|-------|-------------------|
| U1 | As a user, I want to see a map of dangerous locations for a selected time period | Map with heatmap/points, date filter |
| U2 | As a user, I want to switch between display modes (heatmap, points, districts) | Three modes, switcher in sidebar |
| U3 | As a user, I want to filter by confidence level | Slider from 0 to 1, map updates |
| U4 | As a user, I want to check route safety from A to B | Two-point input, route visualization with warnings |
| U5 | As a user, I want to see details for a specific point | Popup with address, date, post excerpt, confidence |
| U6 | As a user, I want to see statistics for the current filter | Counters: points, streets, districts, unresolved |

### Admin

| ID | Story | Acceptance Criteria |
|----|-------|-------------------|
| A1 | As an admin, I want to see a dashboard with attention-needed counters | Needs attention, Pending review, System health, Today's stats |
| A2 | As an admin, I want to resolve unrecognized posts | Table with confirm/edit/reject, mini-map per post |
| A3 | As an admin, I want to manage the slang dictionary | Pending/Active/Rejected tabs, approve/edit/reject |
| A4 | As an admin, I want to see unrecognized tokens and add them to the dictionary | List by frequency, add-to-dictionary/dismiss |
| A5 | As an admin, I want to see worker and pipeline status | Worker health indicator, last run time |
| A6 | As an admin, I want to manually trigger the pipeline | Trigger button, execution status |
| A7 | As an admin, I want to retry processing of failed posts | Retry button per post |

---

## 5. Functional Requirements

### FR-1: Data Ingestion (Telegram)

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-1.1 | Incremental post fetching from Telegram channel via MTProto (Telethon) | Must |
| FR-1.2 | Deduplication by `telegram_id` | Must |
| FR-1.3 | Session persistence — automatic recovery after restart | Must |
| FR-1.4 | Rate limit handling (FloodWaitError, exponential backoff) | Must |
| FR-1.5 | Deleted message tracking (soft-delete) | Should |
| FR-1.6 | Bootstrap mode — fetch historical posts on first run | Must |

### FR-2: Text Processing

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-2.1 | Preprocessing: emoji removal, Unicode normalization, slang replacement | Must |
| FR-2.2 | Rule-based location extraction with fuzzy matching (rapidfuzz) | Must |
| FR-2.3 | Abbreviation expansion (вул., пр., бульв., etc.) | Must |
| FR-2.4 | spaCy NER as fallback for posts without rule-based results | Should |
| FR-2.5 | Ukrainian and Russian language support | Must |
| FR-2.6 | Unrecognized token logging with occurrence counting | Should |

### FR-3: Geocoding

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-3.1 | Fallback chain: cache → Photon (local) → Nominatim → district dictionary | Must |
| FR-3.2 | Geocode cache with 90-day TTL | Must |
| FR-3.3 | Bounding box validation (out-of-city results → fallback or out_of_bounds) | Must |
| FR-3.4 | Street rename mapping (old → new) | Should |
| FR-3.5 | Nominatim rate limiting (1 req/sec, queue max 500) | Must |
| FR-3.6 | Adaptive precision: exact point / street centroid / district polygon | Must |

### FR-4: Confidence Scoring

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-4.1 | Weighted confidence: `(extraction_score * 0.5) + (geocoder_score * 0.5)` | Must |
| FR-4.2 | Thresholds: >= 0.7 auto-resolved, 0.4-0.7 flagged, < 0.4 unresolved | Must |
| FR-4.3 | Confidence penalties: NER-only (x 0.5), out-of-bounds (x 0.3), fuzzy 80-89% (x 0.8) | Must |

### FR-5: Public Map

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-5.1 | Leaflet map with OSM tiles, bbox-based data loading | Must |
| FR-5.2 | Heatmap mode with time-decay intensity | Must |
| FR-5.3 | Points mode with clustering (markercluster) | Must |
| FR-5.4 | Districts mode with polygon overlay | Must |
| FR-5.5 | Date range filter + quick buttons (Today/Week/Month/All) | Must |
| FR-5.6 | Confidence threshold slider | Should |
| FR-5.7 | Route safety check (A → B via OSRM + proximity warnings) | Should |
| FR-5.8 | Statistics sidebar (counts per filter) | Should |
| FR-5.9 | Popup with details on point click | Must |
| FR-5.10 | Collapsible sidebar | Should |

### FR-6: Admin Panel

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-6.1 | JWT authentication (single admin account) | Must |
| FR-6.2 | Dashboard with action-oriented counters | Must |
| FR-6.3 | Unresolved posts management (confirm/edit/reject) | Must |
| FR-6.4 | Slang dictionary management (pending queue, approve/edit/reject) | Must |
| FR-6.5 | Unrecognized tokens review (add-to-dictionary/dismiss) | Should |
| FR-6.6 | Worker health monitoring | Should |
| FR-6.7 | Manual pipeline trigger | Should |
| FR-6.8 | Re-queue failed posts | Should |

### FR-7: Self-Learning

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-7.1 | Auto-detect slang → pending entry in dictionary | Should |
| FR-7.2 | Activation threshold: 3+ confirmations or admin approval | Should |
| FR-7.3 | Auto-demotion: 90 days without usage → pending | Nice-to-have |

---

## 6. Non-Functional Requirements

### NFR-1: Performance

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-1.1 | API response time for map endpoints | < 500ms (p95) |
| NFR-1.2 | Heatmap endpoint response (aggregated grid) | < 300ms (p95) |
| NFR-1.3 | Pipeline throughput | 50k posts/day |
| NFR-1.4 | Frontend debounce on filters | 300ms |
| NFR-1.5 | Frontend debounce on map move | 500ms |
| NFR-1.6 | In-flight request cancellation | RxJS switchMap |

### NFR-2: Reliability

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-2.1 | Pipeline failure isolation | Per-post savepoints, batch doesn't fail on single post error |
| NFR-2.2 | Worker crash recovery | Advisory lock auto-release, resume from `last_message_id` |
| NFR-2.3 | Max retries per post | 3, then permanent_failure |
| NFR-2.4 | External service degradation | Graceful fallback (Nominatim, OSRM) |

### NFR-3: Scalability

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-3.1 | Architecture ready for Celery migration | Minimal code changes |
| NFR-3.2 | Multi-city support | Parametrized by city_id |
| NFR-3.3 | AI provider abstraction | Interface-based, switchable via config |

### NFR-4: Security

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-4.1 | Admin endpoints protected by JWT | Must |
| NFR-4.2 | API rate limiting | 60 req/min public, 120 req/min admin |
| NFR-4.3 | Telegram credentials not in code | ENV vars |
| NFR-4.4 | No public access to raw Telegram data | API returns only processed/sanitized data |

### NFR-5: Usability

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-5.1 | Visual style: Swiss Minimal | Clean, magazine-like aesthetic |
| NFR-5.2 | Mobile-friendly map | Responsive layout |
| NFR-5.3 | Admin panel usability | Action-oriented, not status-oriented |

---

## 7. Data Model

Detailed DB schema is described in the [MVP Design Document](./mvp-design-plan.md#database-schema).

**Key entities:**
- `posts` — raw and cleaned text from Telegram
- `locations` — geolocations (PostGIS geometry) with confidence scoring
- `cities` — city configuration (bbox, zoom)
- `slang_dictionary` — slang dictionary with self-learning workflow
- `street_renames` — street renames (old → new)
- `geocode_cache` — geocoding cache
- `districts` — district boundaries (polygons)
- `unrecognized_tokens` — unrecognized tokens for admin review
- `channel_state` — incremental sync state
- `worker_heartbeat` — worker process heartbeat

---

## 8. System Architecture

```
Frontend (Angular + Leaflet)
         |
         | REST API (JSON / GeoJSON)
         v
Backend (FastAPI)          Worker (APScheduler + Pipeline)
         |                          |
         +----------+---------------+
                    v
            PostgreSQL + PostGIS
                    ^
                    |
         Photon (local geocoder)
```

- **Two processes, shared DB** — API reads, Worker writes
- **No in-process coupling** — independent restart/scaling
- **Docker Compose** — single deployment unit for MVP

---

## 9. External Dependencies

| Service | Role | Availability | Fallback |
|---------|------|-------------|----------|
| Telegram MTProto | Data source | Requires account + session | N/A — primary data source |
| Photon (local) | Primary geocoder | Self-hosted, high availability | Nominatim |
| Nominatim (public) | Fallback geocoder | Public, no SLA, rate-limited | District dictionary |
| OSRM (public) | Route building | Public, no SLA | HTTP 503 + user message |
| OpenStreetMap tiles | Map rendering | Public, high availability | N/A |

---

## 10. Out of Scope (MVP)

- Multi-user auth (single admin only)
- WebSocket real-time updates (polling sufficient for hourly data)
- Street LineString rendering (all locations as Points, except districts)
- Mobile native app
- Push notifications
- Multi-language UI
- Analytics / reporting beyond basic stats
- Public API for third-party consumers
- Celery + Redis (APScheduler for MVP)
- Custom Nominatim instance

---

## 11. Success Metrics

| Metric | Target | How to Measure |
|--------|--------|---------------|
| Posts processed per day | >= 1000 | Worker logs |
| Location extraction rate | >= 60% of posts yield at least one location | `processed / total` ratio |
| High confidence rate | >= 40% of locations with confidence >= 0.7 | DB query |
| Geocoding cache hit rate | >= 80% after warmup | `geocode_cache.hit_count` stats |
| Pipeline cycle duration | < 30 min | Worker logs |
| Admin unresolved queue growth | Stable or decreasing weekly | `/api/admin/stats` |

---

## 12. Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Telegram account ban | System stops ingesting data | Medium | Dedicated account, respectful rate limits, session persistence |
| Low extraction accuracy | Map data unreliable | Medium | Rule-based + NER combo, admin review queue, self-learning dictionary |
| Photon/Nominatim data staleness | Wrong geocoding for renamed streets | Low | `street_renames` table, periodic Photon data refresh |
| OSRM downtime | Route check unavailable | Low | Graceful degradation (503), feature non-critical |
| Slang evolution | Dictionary becomes outdated | Medium | Self-learning workflow, unrecognized token tracking, admin tools |
| High post volume spike | Pipeline can't keep up | Low | Batch processing, advisory locks, scalability thresholds trigger Celery migration |

---

## 13. Glossary

| Term | Definition |
|------|-----------|
| Confidence | Numerical score 0.0-1.0 representing system certainty about a location's correctness |
| Extraction score | Quality of address extraction from text |
| Geocoder score | Quality of geocoding an address into coordinates |
| Geo type | Semantic location type: point, street, area, district |
| Heatmap intensity | Zone intensity on heatmap with time-decay |
| Unresolved | A post for which the system could not determine a location with sufficient confidence |
| Slang dictionary | Dictionary of slang and abbreviations mapping informal names to official ones |
| Pipeline | Processing sequence: fetch → preprocess → analyze → geocode → normalize |
