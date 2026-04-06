# Phase 3: Public API & Map Frontend

**Goal:** Display processed danger locations on an interactive public map with filtering, heatmap, and route-check features.

---

## File Map

### New files

**Backend**

- `backend/app/repositories/city_repository.py` — `get_all()` → all City rows
- `backend/app/api/routers/route.py` — `GET /api/route/check` (OSRM + ST_DWithin)
- `backend/app/core/response_cache.py` — async TTL cache (dict + asyncio.Lock)

**Frontend**

- `frontend/src/app/core/services/map-api.service.ts` — typed HTTP client for all public endpoints
- `frontend/src/app/features/map/services/filter.service.ts` — signal-based shared filter state
- `frontend/src/app/features/map/services/map-data.service.ts` — data loading with debounce + switchMap
- `frontend/src/app/features/map/components/filter-panel/filter-panel.component.{ts,html,scss}`
- `frontend/src/app/features/map/components/stats/stats.component.{ts,html,scss}`
- `frontend/src/app/features/map/components/route-check/route-check.component.{ts,html,scss}`

### Modified files

**Backend**

- `backend/app/api/routers/public.py` — add `/api/heatmap`, `/api/stats`, `/api/cities`, `/api/districts`; extend `/api/locations` with `date_from`, `date_to`, `geo_type`, `post_excerpt`
- `backend/app/repositories/location_repository.py` — add `get_heatmap_points()`, `get_stats()`, `get_locations_near_line()`
- `backend/app/core/config.py` — add `osrm_url`, `api_cache_ttl_seconds`
- `backend/app/api/main.py` — add slowapi limiter, register route router
- `backend/pyproject.toml` — add `httpx`, `slowapi`
- `.env.example` — add `OSRM_URL`

**Frontend**

- `frontend/src/app/features/map/map.component.{ts,html,scss}` — full map implementation
- `frontend/src/app/app.config.ts` — add `provideHttpClient()`
- `frontend/src/app/shared/styles/_tokens.scss` — add z-index, transition, shadow tokens

---

## Tasks

### Task 1: Backend — extend /api/locations (date range + geo_type + excerpt)

**Files:** `location_repository.py`, `public.py`

Current `get_map_locations()` has: `channel_id`, `min_confidence`, `bbox`.
Add: `date_from: datetime | None`, `date_to: datetime | None`, `geo_type: str | None`.
Add to SELECT: `Post.cleaned_text.label("post_excerpt_raw")`.
Add WHERE clauses for the new optional params.
Response: include `post_excerpt` = first 150 chars of `cleaned_text`.

- [x] Add `date_from`, `date_to`, `geo_type` params to `get_map_locations()` + WHERE clauses
- [x] Add `Post.cleaned_text` to SELECT
- [x] Add `date_from`, `date_to`, `geo_type` query params to the `GET /api/locations` handler
- [x] Include `post_excerpt` (sliced to 150 chars) in each feature's `properties`
- [x] Manual verify: `curl "http://localhost:8000/api/locations?geo_type=address"` returns features with `post_excerpt`

---

### Task 2: Backend — /api/cities + CityRepository

**Files:** `city_repository.py` (new), `public.py`

`CityRepository.get_all()`:

```python
result = await self._session.execute(select(City))
return list(result.scalars().all())
```

`GET /api/cities` response:

```json
[{
  "id": 1,
  "name": "Одеса",
  "name_ru": "Одесса",
  "bbox": { "north": ..., "south": ..., "east": ..., "west": ... },
  "center": { "lat": (north+south)/2, "lng": (east+west)/2 },
  "default_zoom": 13
}]
```

- [x] Create `CityRepository` with `get_all()`
- [x] Add `GET /api/cities` to `public.py` using `CityRepository`
- [x] Manual verify: returns Odesa with computed center

---

### Task 3: Backend — /api/heatmap (time-decay points)

**Files:** `location_repository.py`, `public.py`

`get_heatmap_points()` — returns `list[tuple[float, float, float]]` (lat, lng, weight).
Time-decay formula: `weight = confidence * GREATEST(0.1, EXP(-(days_old / 14.0)))`
where `days_old = EXTRACT(EPOCH FROM (NOW() - post_date)) / 86400`.

Use raw SQL via `text()` for the EXP expression. Accept same filter params as `get_map_locations` (minus `geo_type`).

`GET /api/heatmap` query params: `west`, `south`, `east`, `north`, `min_confidence`, `date_from`, `date_to`.
Response: `{ "points": [[lat, lng, weight], ...] }`

- [x] Add `get_heatmap_points()` to `LocationRepository` with time-decay SQL
- [x] Add `GET /api/heatmap` to `public.py`
- [x] Manual verify: returns non-empty array of `[lat, lng, weight]` for Odesa bbox

---

### Task 4: Backend — /api/stats

**Files:** `location_repository.py`, `public.py`

`get_stats()` — single SQL query with multiple filtered counts:

```sql
SELECT
  COUNT(*) FILTER (WHERE true) AS total,
  COUNT(*) FILTER (WHERE post_date >= NOW() - INTERVAL '1 day') AS today,
  COUNT(*) FILTER (WHERE post_date >= NOW() - INTERVAL '7 days') AS this_week,
  COUNT(*) FILTER (WHERE post_date >= NOW() - INTERVAL '30 days') AS this_month,
  COUNT(*) FILTER (WHERE locations.geo_type = 'address') AS geo_address,
  COUNT(*) FILTER (WHERE locations.geo_type = 'intersection') AS geo_intersection,
  COUNT(*) FILTER (WHERE locations.geo_type = 'district') AS geo_district,
  COUNT(*) FILTER (WHERE locations.geo_type = 'direction') AS geo_direction
FROM locations JOIN posts ON ...
WHERE [standard active-location filters: channel_id, is_deleted, out_of_bounds, confidence]
```

`GET /api/stats` accepts `min_confidence` (default 0.4).
Response:

```json
{
  "total": 450,
  "today": 3,
  "this_week": 18,
  "this_month": 67,
  "by_geo_type": {
    "address": 210,
    "intersection": 90,
    "district": 80,
    "direction": 70
  }
}
```

- [x] Add `get_stats()` to `LocationRepository` with a single aggregate query
- [x] Add `GET /api/stats` to `public.py`
- [x] Manual verify: returns plausible counts

---

### Task 5: Backend — /api/districts

**Files:** `public.py`, read `backend/app/models/district.py` first to confirm fields.

Query: `SELECT id, name, ST_AsGeoJSON(geometry) FROM districts WHERE city_id = :city_id`

Returns GeoJSON FeatureCollection. Each feature has `name` property.

`GET /api/districts?city_id=1`

- [x] Read `backend/app/models/district.py` to confirm geometry column and `city_id` FK
- [x] Add `GET /api/districts` to `public.py` (raw SQLAlchemy `select()` + `ST_AsGeoJSON`)
- [x] Manual verify: returns district polygons covering Odesa

---

### Task 6: Backend — /api/route/check (OSRM)

**Files:** `config.py`, `route.py` (new), `location_repository.py`, `main.py`, `pyproject.toml`, `.env.example`

**Config additions:**

```python
osrm_url: str = "https://router.project-osrm.org"
```

**OSRM request format:**
`GET {osrm_url}/route/v1/driving/{orig_lng},{orig_lat};{dest_lng},{dest_lat}?geometries=geojson&overview=full`
Note: OSRM uses (longitude, latitude) order.

**`get_locations_near_line()`** in `LocationRepository`:

```python
async def get_locations_near_line(
    self, geojson_line: str, radius_meters: float,
    channel_id: int, hours: int = 24, min_confidence: float = 0.4,
) -> list[dict]:
```

Use `ST_DWithin(geometry::geography, ST_GeomFromGeoJSON(:line)::geography, :radius)` — geography cast gives accurate meters.

**`route.py` handler query params:**

```
origin_lat, origin_lng, dest_lat, dest_lng: float (required)
radius_meters: float = 100.0 (ge=10, le=500)
hours: int = 24 (ge=1, le=168)
min_confidence: float = 0.4
```

**Response:**

```json
{
  "route": { "type": "LineString", "coordinates": [[lng, lat], ...] },
  "danger_locations": [
    { "id": 1, "address": "...", "confidence": 0.8,
      "lat": 46.47, "lng": 30.72, "post_date": "2025-01-15T10:00:00" }
  ],
  "danger_count": 3
}
```

On OSRM failure: raise `AppError` with status 503, code `ROUTE_SERVICE_UNAVAILABLE`.

- [x] Add `osrm_url` to `Settings` in `config.py`
- [x] Add `OSRM_URL=https://router.project-osrm.org` to `.env.example`
- [x] Add `httpx>=0.27` to `pyproject.toml` and run `uv sync`
- [x] Create `route.py` router: call OSRM via `httpx.AsyncClient`, parse GeoJSON route
- [x] Add `get_locations_near_line()` to `LocationRepository` (geography cast for accurate radius)
- [x] Register `route.router` in `main.py`
- [x] Manual verify: request with two Odesa coordinates returns a route polyline + `danger_count`

---

### Task 7: Backend — response cache (TTL)

**Files:** `response_cache.py` (new), `config.py`, `public.py`

`response_cache.py` — async TTL cache:

```python
class ResponseCache:
    _store: dict[str, tuple[Any, float]]  # key -> (value, expires_at)
    _lock: asyncio.Lock

    async def get(self, key: str) -> Any | None: ...
    async def set(self, key: str, value: Any, ttl: int) -> None: ...
    async def invalidate_all(self) -> None: ...

response_cache = ResponseCache()  # module-level singleton
```

Apply as inline logic in handlers for `/api/locations`, `/api/heatmap`, `/api/stats`.
Cache key = `f"{endpoint}:{str(sorted(request.query_params.items()))}"`.
TTL = `settings.api_cache_ttl_seconds` (default 600 = 10 min).

Do **not** cache `/api/route/check` (user-specific inputs) or `/api/cities` (static, startup-loaded).
Cross-process cache invalidation after pipeline run is deferred — TTL of 10 min is acceptable for MVP (pipeline is hourly).

Add `api_cache_ttl_seconds: int = 600` to `Settings`.

- [x] Add `api_cache_ttl_seconds: int = 600` to `Settings` in `config.py`
- [x] Create `ResponseCache` singleton in `backend/app/core/response_cache.py`
- [x] Apply cache to `/api/locations`, `/api/heatmap`, `/api/stats` handlers in `public.py`
- [x] Manual verify: log shows cache hit on second identical request (add `DEBUG` log in `get()`)

---

### Task 8: Backend — rate limiting (slowapi)

**Files:** `main.py`, `pyproject.toml`

Run `uv add slowapi` (adds to `pyproject.toml`).

In `main.py`:

```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
```

Apply `@limiter.limit("60/minute")` to every handler in `public.py` and `route.py`.
Each handler needs `request: Request` as first param for slowapi to work.

- [x] Add `slowapi` via `uv add slowapi`
- [x] Configure `Limiter` in `main.py`
- [x] Add `request: Request` param + `@limiter.limit("60/minute")` to all public handlers
- [x] Manual verify: 61st rapid request returns HTTP 429

---

### Task 9: Backend — code quality

- [x] `cd backend && ruff check --fix . && ruff format .`
- [x] `mypy app/core/ app/services/`
- [x] Fix all reported issues before proceeding to frontend

---

### Task 10: Frontend — map-api.service.ts

**File:** `frontend/src/app/core/services/map-api.service.ts`

Define TypeScript interfaces (can live in the same file for now):

```typescript
export interface LocationProperties {
  id: number;
  post_id: number;
  address: string;
  street_name: string | null;
  geo_type: string;
  confidence: number;
  resolved: boolean;
  resolved_by: string | null;
  post_date: string | null;
  post_excerpt: string | null;
}
export interface LocationsResponse {
  type: "FeatureCollection";
  features: LocationFeature[];
}
export interface HeatmapResponse {
  points: [number, number, number][];
}
export interface StatsResponse {
  total: number;
  today: number;
  this_week: number;
  this_month: number;
  by_geo_type: Record<string, number>;
}
export interface CityResponse {
  id: number;
  name: string;
  name_ru: string;
  bbox: { north: number; south: number; east: number; west: number };
  center: { lat: number; lng: number };
  default_zoom: number;
}
export interface RouteCheckResponse {
  route: { type: "LineString"; coordinates: [number, number][] };
  danger_locations: RouteDangerLocation[];
  danger_count: number;
}
```

Service methods all return `Observable<T>` via `HttpClient.get<T>()`. Use `HttpParams` to build query strings (omit undefined/null values).

- [x] Create `map-api.service.ts` with all interfaces and HTTP methods
- [x] Verify `provideHttpClient()` is in `frontend/src/app/app.config.ts` (add if missing)

---

### Task 11: Frontend — FilterService

**File:** `frontend/src/app/features/map/services/filter.service.ts`

```typescript
export type DisplayMode = "heatmap" | "points" | "districts";
export type DatePreset = "today" | "week" | "month" | "all";

@Injectable({ providedIn: "root" })
export class FilterService {
  readonly dateFrom = signal<Date | null>(null);
  readonly dateTo = signal<Date | null>(null);
  readonly minConfidence = signal(0.4);
  readonly displayMode = signal<DisplayMode>("points");

  readonly activeFilters = computed(() => ({
    date_from: toIsoOrUndefined(this.dateFrom()),
    date_to: toIsoOrUndefined(this.dateTo()),
    min_confidence: this.minConfidence(),
  }));

  applyDatePreset(preset: DatePreset): void {
    /* compute and set dateFrom/dateTo */
  }
  reset(): void {
    /* reset all signals to defaults */
  }
}
```

- [x] Create `FilterService` with all signals
- [x] Implement `applyDatePreset()`: 'today' = last 24h, 'week' = last 7 days, 'month' = last 30 days, 'all' = null/null
- [x] `activeFilters` computed signal combining date + confidence into API param object
- [x] `reset()` restores all signals to defaults

---

### Task 12: Frontend — MapDataService

**File:** `frontend/src/app/features/map/services/map-data.service.ts`

`@Injectable()` — **no** `providedIn: 'root'`. Provided at `MapComponent` level to tie lifecycle to the map page.

Key patterns:

- `toSignal(filterService.activeFilters)` → `combineLatest` with `bboxChanged$` Subject
- Debounce: filters `300ms`, bbox `500ms`
- `switchMap` on each change → calls API → cancel in-flight
- `toSignal()` to expose results as signals
- Stats: `merge(of(null), interval(5 * 60 * 1000)).pipe(switchMap(() => api.getStats(...)))`
- `takeUntilDestroyed()` on all subscriptions

Exposes:

```typescript
readonly bboxChanged$ = new Subject<L.LatLngBounds>();
readonly locations: Signal<LocationsResponse>;
readonly heatmapPoints: Signal<[number, number, number][]>;
readonly stats: Signal<StatsResponse | null>;
```

- [x] Create `MapDataService` skeleton with `bboxChanged$` Subject
- [x] Build locations stream: `toObservable(filterService.activeFilters)` + `bboxChanged$` + debounce 300ms/500ms + `switchMap` → `api.getLocations()`
- [x] Build heatmap stream: same pattern → `api.getHeatmap()`
- [x] Build stats stream: `interval(5min)` + immediate + `switchMap` → `api.getStats()`
- [x] Convert all streams to signals via `toSignal()` with safe initial values
- [x] Verify: `takeUntilDestroyed(destroyRef)` on all subscriptions

---

### Task 13: Frontend — MapComponent (full implementation)

**Files:** `map.component.ts`, `map.component.html`, `map.component.scss`

**Component decorator:**

```typescript
@Component({
  providers: [MapDataService],  // scoped to map page
  imports: [FilterPanelComponent, StatsComponent, RouteCheckComponent],
  ...
})
```

**Layer strategy (Display Modes):**

- `'heatmap'`: show `HeatLayer` (leaflet.heat), hide marker cluster
- `'points'`:
  - zoom < 14: auto-show HeatLayer (lazy load), hide marker cluster
  - zoom ≥ 14: show marker cluster, hide HeatLayer
- `'districts'`: show district polygons (GeoJSON layer), hide both above

**Effects:**

```typescript
// Update markers
effect(() => {
  const data = mapData.locations();
  updateMarkerCluster(data);
});
// Update heatmap
effect(() => {
  const pts = mapData.heatmapPoints();
  updateHeatLayer(pts);
});
// Switch layers on mode change or zoom change
effect(() => {
  updateLayerVisibility(filterService.displayMode(), currentZoom());
});
```

**Popup content:**

```html
<b>{address}</b><br />
<span class="geo-badge">{geo_type}</span>
<span class="confidence">{confidence * 100 | toFixed(0)}%</span><br />
<small>{post_date | date:'dd.MM.yyyy'}</small>
{#if post_excerpt}
<p class="excerpt">{post_excerpt}</p>
{/if}
```

**Map move:** `map.on('moveend', () => mapData.bboxChanged$.next(map.getBounds()))`

**Layout (HTML):** Full-viewport map + fixed right sidebar (collapsible on mobile). StatsComponent pinned top-left over the map.

**Districts layer:** Fetch `/api/districts?city_id=1` once on init, add as GeoJSON layer (styled with semi-transparent fill), toggle visibility with mode.

- [x] Check `package.json` for `leaflet.markercluster` + `@types/leaflet.markercluster` — install if missing
- [x] Install `leaflet.heat` types if needed (`@types/leaflet.heat` or declare module)
- [x] Add `MapDataService` to `providers`, import child components
- [x] Initialize Leaflet map, markercluster group, heatmap layer, district GeoJSON layer
- [x] Load district data once on init (`HttpClient` directly or `MapApiService`)
- [x] `map.on('moveend')` → `bboxChanged$.next(map.getBounds())`
- [x] `map.on('zoomend')` → update `currentZoom` signal, recalculate layer visibility
- [x] `effect()` to update markercluster when `locations` changes
- [x] `effect()` to update heatmap layer when `heatmapPoints` changes
- [x] `effect()` to toggle layer visibility when `displayMode` or `currentZoom` changes
- [x] Popup: address, geo_type badge, confidence %, post_date, excerpt
- [x] HTML layout: `<div id="map">` + sidebar div with child components
- [x] SCSS: full-height map, fixed sidebar (right), z-index layering, mobile breakpoint

---

### Task 14: Frontend — FilterPanelComponent

**Files:** `filter-panel.component.{ts,html,scss}`

Standalone component. Injects `FilterService`. No `@Input()` needed — reads/writes signals directly.

**Template structure:**

```
[Today] [Week] [Month] [All]        ← quick date buttons
From: [date input]  To: [date input]
──
Mode: ○ Heatmap  ○ Points  ○ Districts
──
Min confidence: ─●─────  40%
──
[Reset]
```

Mobile: hidden by default, show/hide via `isOpen = signal(false)` + toggle button (hamburger or ☰).

- [x] Create component injecting `FilterService`
- [x] Quick date buttons calling `filterService.applyDatePreset(preset)`
- [x] Date inputs two-way bound to `filterService.dateFrom` / `filterService.dateTo` (use `model()` or manual `(input)` event)
- [x] Display mode radio group (value = `'heatmap' | 'points' | 'districts'`)
- [x] Confidence range input (`type="range"`, min=0, max=1, step=0.05) + label showing percentage
- [x] Reset button calls `filterService.reset()`
- [x] Mobile toggle: `isOpen` signal, `@if (isOpen())` wrapper
- [x] Swiss Minimal styles: 1px border panel, white bg, 16px padding, no shadows

---

### Task 15: Frontend — StatsComponent

**Files:** `stats.component.{ts,html,scss}`

Standalone. Injects `MapDataService`.

```typescript
readonly stats = inject(MapDataService).stats;
```

Template (compact inline layout):

```
450 total  ·  3 today  ·  18 this week  ·  67 this month
```

Show `—` while `stats() === null`.

Position in parent: pinned top-left corner over the map (absolutely positioned).

- [x] Create component reading `MapDataService.stats` signal
- [x] Show `—` placeholder while null
- [x] Display total / today / this_week / this_month inline
- [x] Swiss Minimal styles: white bg, thin border, small font, padding 6px 12px

---

### Task 16: Frontend — RouteCheckComponent

**Files:** `route-check.component.{ts,html,scss}`

Standalone. Injects `MapApiService`.
Emits result to parent via `output()`.

```typescript
readonly routeResult = output<RouteCheckResponse | null>();
```

**Template:**

```
Route Check
Origin:  [lat, lng input]
Dest:    [lat, lng input]
Hours:   [slider 1–168, default 24]
Radius:  [slider 10–500m, default 100m]
         [Check Route]

Result: "3 danger zones on route" (red) / "Route is clear ✓" (green)
```

Validate lat ∈ [-90, 90], lng ∈ [-180, 180]. Show inline error on invalid input.
Show loading spinner on button during request.
On result → `routeResult.emit(response)` → parent draws polyline + danger markers.
On OSRM 503 → show "Route service unavailable, try again".

Parent (`MapComponent`) handles `(routeResult)` output:

- Clear previous route layer
- Draw route polyline (blue, dashed)
- Add red markers for `danger_locations`

- [x] Create component with lat/lng inputs + hour/radius sliders
- [x] Input validation (reactive form or manual signal-based)
- [x] Call `MapApiService.checkRoute()` on button click with `switchMap` (cancel previous)
- [x] Show inline result: danger count (red) or "clear" (green)
- [x] Emit result via `output()`
- [x] Parent `MapComponent`: handle `(routeResult)` — draw/clear route layer + danger markers

---

### Task 17: Frontend — lint + E2E verify

- [x] `cd frontend && ng lint` — fix all errors
- [x] Open map in browser, verify OSM tiles load
- [x] Confirm locations appear as clustered markers
- [x] Toggle to Heatmap mode → leaflet.heat overlay appears
- [x] Toggle to Districts mode → district polygons visible
- [x] Filter panel: date preset "Today" → markers update
- [x] Confidence slider → markers update
- [x] Stats panel shows live counts
- [x] Route check: enter two Odesa coords → polyline drawn + danger count shown

---

## End-of-Phase Verification

- [x] `docker compose up` → all services healthy
- [x] `GET /api/health` → `{"status":"ok"}`
- [x] `GET /api/cities` → returns Odesa with center + bbox
- [x] `GET /api/locations?west=30.6&south=46.3&east=30.8&north=46.6` → GeoJSON features with `post_excerpt`
- [x] `GET /api/heatmap?west=30.6&south=46.3&east=30.8&north=46.6` → `{"points":[[lat,lng,w],...]}`
- [x] `GET /api/stats` → counts object
- [x] `GET /api/districts?city_id=1` → district polygon FeatureCollection
- [x] `GET /api/route/check?origin_lat=46.48&origin_lng=30.72&dest_lat=46.46&dest_lng=30.74` → route + danger_count
- [x] 61st rapid request → HTTP 429
- [x] `ruff check .` in `backend/` → no errors
- [x] `ng lint` in `frontend/` → no errors
- [x] Public map fully functional in browser

## Deliverable

Public map with live danger data, heatmap, district view, filter panel, stats, and route check.
