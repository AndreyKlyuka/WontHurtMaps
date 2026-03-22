# Code Examples — WontHurtMaps

Reference examples for Claude Code. Follow these patterns exactly when generating new code.
Each section shows the **correct** and **incorrect** approach.

---

## Table of Contents

- [Frontend: Access Modifiers & Field Ordering](#frontend-access-modifiers--field-ordering)
- [Frontend: Readonly Fields & Injected Services](#frontend-readonly-fields--injected-services)
- [Frontend: Type Definitions in Separate Files](#frontend-type-definitions-in-separate-files)
- [Frontend: Explicit Return Types](#frontend-explicit-return-types)
- [Frontend: No Logic in Templates](#frontend-no-logic-in-templates)
- [Frontend: Smart vs Dumb Components](#frontend-smart-vs-dumb-components)
- [Frontend: RxJS Business Logic — Readable Streams](#frontend-rxjs-business-logic--readable-streams)
- [Frontend: Service Pattern](#frontend-service-pattern)
- [Frontend: Design System SCSS Tokens](#frontend-design-system-scss-tokens)
- [Backend: Function Structure & Naming](#backend-function-structure--naming)
- [Backend: Type Hints & Return Types](#backend-type-hints--return-types)
- [Backend: Router → Service → Repository](#backend-router--service--repository)
- [Backend: Error Handling](#backend-error-handling)
- [Backend: Logging](#backend-logging)
- [Backend: Config via pydantic-settings](#backend-config-via-pydantic-settings)
- [Backend: SQLAlchemy 2.x Model](#backend-sqlalchemy-2x-model)

---

## Frontend: Access Modifiers & Field Ordering

All fields and methods must have explicit access modifiers.
Order: `public` → `protected` → `private`. Within each group: fields first, then methods.

```typescript
// --- CORRECT ---
export class FilterPanelComponent {
  // public fields
  public readonly collapsed = signal(false);

  // protected fields (if any)

  // private fields
  private readonly filterService = inject(FilterService);
  private readonly destroyRef = inject(DestroyRef);

  // public methods
  public toggle(): void {
    this.collapsed.update((v) => !v);
  }

  // private methods
  private resetFilters(): void {
    this.filterService.reset();
  }
}
```

```typescript
// --- INCORRECT ---
export class FilterPanelComponent {
  private filterService = inject(FilterService);   // no readonly, mixed order
  collapsed = signal(false);                        // no access modifier
  destroyRef = inject(DestroyRef);                  // no access modifier, no readonly

  toggle() {                                        // no access modifier, no return type
    this.collapsed.update((v) => !v);
  }

  private resetFilters() {                          // no return type
    this.filterService.reset();
  }
}
```

---

## Frontend: Readonly Fields & Injected Services

Injected services and fields that are not reassigned must be `readonly`.

```typescript
// --- CORRECT ---
export class MapContainerComponent {
  private readonly locationApi = inject(LocationApiService);
  private readonly filterService = inject(FilterService);
  private readonly notificationService = inject(NotificationService);

  public readonly mapConfig: MapConfig = MAP_DEFAULTS;
}
```

```typescript
// --- INCORRECT ---
export class MapContainerComponent {
  private locationApi = inject(LocationApiService);     // missing readonly
  private filterService = inject(FilterService);        // missing readonly
  private notificationService = inject(NotificationService);

  mapConfig: MapConfig = MAP_DEFAULTS;                  // missing access modifier and readonly
}
```

---

## Frontend: Type Definitions in Separate Files

Types, interfaces, and enums belong in dedicated files — not inline in components or services.

```
features/map/
  models/
    display-mode.type.ts
    map-config.interface.ts
    location-filter.interface.ts
  components/
    filter-panel/
      filter-panel.component.ts
```

```typescript
// --- CORRECT ---
// models/display-mode.type.ts
export type DisplayMode = 'heatmap' | 'points' | 'districts';

// models/map-config.interface.ts
export interface MapConfig {
  readonly center: [number, number];
  readonly zoom: number;
  readonly minZoom: number;
  readonly maxZoom: number;
}

// models/location-filter.interface.ts
export interface LocationFilter {
  readonly bbox: string;
  readonly dateFrom?: string;
  readonly dateTo?: string;
  readonly minConfidence?: number;
}
```

```typescript
// --- INCORRECT ---
// Inline types inside a component file
@Component({ ... })
export class FilterPanelComponent {
  displayMode = signal<'heatmap' | 'points' | 'districts'>('heatmap');  // inline union type

  onModeChange(mode: 'heatmap' | 'points' | 'districts'): void {       // duplicated inline type
    this.displayMode.set(mode);
  }
}
```

---

## Frontend: Explicit Return Types

All functions and methods must declare their return type explicitly.

```typescript
// --- CORRECT ---
public toggle(): void {
  this.collapsed.update((v) => !v);
}

public getLocations(filter: LocationFilter): Observable<FeatureCollection> {
  return this.http.get<FeatureCollection>('/api/locations', { params });
}

private buildParams(filter: LocationFilter): HttpParams {
  return new HttpParams().set('bbox', filter.bbox);
}
```

```typescript
// --- INCORRECT ---
toggle() {                            // missing return type, missing access modifier
  this.collapsed.update((v) => !v);
}

getLocations(filter: LocationFilter) { // missing return type
  return this.http.get('/api/locations', { params });  // missing generic type on get()
}

private buildParams(filter: LocationFilter) {  // missing return type
  return new HttpParams().set('bbox', filter.bbox);
}
```

---

## Frontend: No Logic in Templates

Templates must not contain inline arrays, complex expressions, or operations.
Move all data and logic to the component `.ts` file.

```typescript
// --- CORRECT ---
// filter-panel.component.ts
export class FilterPanelComponent {
  public readonly displayModes: readonly DisplayMode[] = ['heatmap', 'points', 'districts'];
  public readonly activeMode = signal<DisplayMode>('heatmap');

  private readonly filterService = inject(FilterService);

  public onModeChange(mode: DisplayMode): void {
    this.activeMode.set(mode);
    this.filterService.setDisplayMode(mode);
  }

  public isActive(mode: DisplayMode): boolean {
    return this.activeMode() === mode;
  }
}
```

```html
<!-- filter-panel.component.html — CORRECT -->
@for (mode of displayModes; track mode) {
  <button
    class="filter-panel__mode-btn"
    [class.active]="isActive(mode)"
    (click)="onModeChange(mode)"
  >
    {{ mode }}
  </button>
}
```

```typescript
// --- INCORRECT ---
export class FilterPanelComponent {
  displayMode = signal<'heatmap' | 'points' | 'districts'>('heatmap');
  // no predefined array, no helper methods
}
```

```html
<!-- filter-panel.component.html — INCORRECT -->
@for (mode of ['heatmap', 'points', 'districts']; track mode) {  <!-- inline array -->
  <button
    [class.active]="displayMode() === mode"                       <!-- expression in template -->
    (click)="onModeChange(mode)"
  >
    {{ mode }}
  </button>
}
```

---

## Frontend: Smart vs Dumb Components

**Smart (container)**: injects services, manages streams, orchestrates data.
**Dumb (presentational)**: receives data via `input()`, emits events via `output()`. No injected services. No business logic.

```typescript
// --- CORRECT: Dumb component ---
// components/location-list/location-list.component.ts
@Component({
  selector: 'whm-location-list',
  standalone: true,
  templateUrl: './location-list.component.html',
  styleUrl: './location-list.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LocationListComponent {
  public readonly locations = input.required<readonly LocationOut[]>();
  public readonly selected = output<LocationOut>();

  public onSelect(location: LocationOut): void {
    this.selected.emit(location);
  }
}
```

```typescript
// --- CORRECT: Smart component ---
// containers/map-page/map-page.component.ts
@Component({
  selector: 'whm-map-page',
  standalone: true,
  imports: [LocationListComponent, MapViewComponent, FilterPanelComponent, AsyncPipe],
  templateUrl: './map-page.component.html',
  styleUrl: './map-page.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MapPageComponent {
  private readonly locationApi = inject(LocationApiService);
  private readonly filterService = inject(FilterService);

  public readonly locations$: Observable<readonly LocationOut[]> = this.filterService.changes$.pipe(
    debounceTime(300),
    switchMap((filters) => this.locationApi.getLocations(filters)),
  );

  public onLocationSelected(location: LocationOut): void {
    this.filterService.focusLocation(location.id);
  }
}
```

```html
<!-- map-page.component.html — CORRECT -->
<whm-filter-panel />
<whm-map-view />
<whm-location-list
  [locations]="locations$ | async"
  (selected)="onLocationSelected($event)"
/>
```

```typescript
// --- INCORRECT: God component — mixes data fetching, UI logic, and presentation ---
@Component({ ... })
export class MapPageComponent {
  locations: LocationOut[] = [];
  collapsed = false;

  constructor(
    private http: HttpClient,            // direct http in component
    private filterService: FilterService // constructor injection
  ) {
    this.http.get('/api/locations').subscribe((data) => {  // subscribe in constructor
      this.locations = data as LocationOut[];               // untyped cast, mutation
    });
  }

  toggle() { this.collapsed = !this.collapsed; }
  selectLocation(loc: any) { /* ... */ }                   // 'any' type
}
```

---

## Frontend: RxJS Business Logic — Readable Streams

Build streams as declarative, composable pipelines. Each operator should have a clear purpose.
Avoid nested subscribes. Use descriptive variable names.

```typescript
// --- CORRECT ---
export class MapPageComponent {
  private readonly locationApi = inject(LocationApiService);
  private readonly filterService = inject(FilterService);

  public readonly locations$: Observable<readonly LocationOut[]> = this.filterService.changes$.pipe(
    debounceTime(300),
    distinctUntilChanged(isEqual),
    switchMap((filters) => this.locationApi.getLocations(filters).pipe(
      catchError((error) => {
        console.error('Failed to fetch locations', error);
        return of([]);
      }),
    )),
    shareReplay({ bufferSize: 1, refCount: true }),
  );

  public readonly locationCount$: Observable<number> = this.locations$.pipe(
    map((locations) => locations.length),
  );
}
```

```typescript
// --- INCORRECT ---
export class MapPageComponent {
  locations: LocationOut[] = [];
  locationCount = 0;

  constructor(
    private locationApi: LocationApiService,
    private filterService: FilterService,
  ) {
    // imperative, nested subscribe, manual state management
    this.filterService.changes$.subscribe((filters) => {
      this.locationApi.getLocations(filters).subscribe(
        (data) => {
          this.locations = data;
          this.locationCount = data.length;
        },
        (error) => {
          console.log(error);                     // console.log instead of console.error
        },
      );
    });
  }
}
```

---

## Frontend: Service Pattern

Services are `readonly`-injected, typed, and focused on a single responsibility.

```typescript
// --- CORRECT ---
// core/services/location-api.service.ts
@Injectable({ providedIn: 'root' })
export class LocationApiService {
  private readonly http = inject(HttpClient);

  public getLocations(filter: LocationFilter): Observable<FeatureCollection> {
    const params: HttpParams = this.buildParams(filter);
    return this.http.get<FeatureCollection>('/api/locations', { params });
  }

  public getHeatmap(filter: HeatmapFilter): Observable<HeatmapResponse> {
    const params: HttpParams = this.buildHeatmapParams(filter);
    return this.http.get<HeatmapResponse>('/api/heatmap', { params });
  }

  private buildParams(filter: LocationFilter): HttpParams {
    let params = new HttpParams().set('bbox', filter.bbox);
    if (filter.dateFrom) {
      params = params.set('date_from', filter.dateFrom);
    }
    if (filter.dateTo) {
      params = params.set('date_to', filter.dateTo);
    }
    if (filter.minConfidence != null) {
      params = params.set('min_confidence', String(filter.minConfidence));
    }
    return params;
  }

  private buildHeatmapParams(filter: HeatmapFilter): HttpParams {
    return new HttpParams()
      .set('bbox', filter.bbox)
      .set('date_from', filter.dateFrom)
      .set('date_to', filter.dateTo);
  }
}
```

```typescript
// --- INCORRECT ---
@Injectable({ providedIn: 'root' })
export class LocationApiService {
  private http = inject(HttpClient);               // missing readonly

  getLocations(filter: LocationFilter) {           // missing access modifier & return type
    return this.http.get('/api/locations', {        // missing generic type
      params: {
        bbox: filter.bbox,
        ...(filter.dateFrom && { date_from: filter.dateFrom }),     // spread in params — hard to debug
        ...(filter.dateTo && { date_to: filter.dateTo }),
        ...(filter.minConfidence != null && { min_confidence: String(filter.minConfidence) }),
      },
    });
  }
}
```

---

## Frontend: Design System SCSS Tokens

```scss
// shared/styles/_tokens.scss
$color-text: #111;
$color-bg: #fff;
$color-danger: #c0392b;
$color-warning: #e67e22;
$color-success: #27ae60;
$color-border: #e0e0e0;
$color-muted: #888;

$font-stack: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
$font-size-sm: 0.75rem;
$font-size-base: 0.875rem;
$font-size-lg: 1.125rem;

$spacing-xs: 4px;
$spacing-sm: 8px;
$spacing-md: 16px;
$spacing-lg: 24px;
$spacing-xl: 32px;

$border: 1px solid $color-border;
$radius-sm: 4px;
$radius-md: 8px;

$breakpoint-sm: 576px;
$breakpoint-md: 768px;
$breakpoint-lg: 1024px;
```

---

## Backend: Function Structure & Naming

Functions follow single responsibility. Max ~25 lines. Extract helpers for longer logic.

```python
# --- CORRECT ---
async def process_post(self, post: TelegramPost) -> ProcessedPost:
    cleaned_text = self._preprocess_text(post.text)
    addresses = self._extract_addresses(cleaned_text)
    locations = await self._geocode_addresses(addresses)
    return ProcessedPost(post_id=post.id, locations=locations)

def _preprocess_text(self, text: str) -> str:
    text = remove_emoji(text)
    text = normalize_unicode(text)
    text = self.slang_service.replace_slang(text)
    return text

def _extract_addresses(self, text: str) -> list[str]:
    expanded = self.abbreviation_service.expand(text)
    return self.street_matcher.find_matches(expanded)
```

```python
# --- INCORRECT ---
async def process(self, post):                    # vague name, no type hints
    # 50+ lines of mixed preprocessing, extraction, geocoding
    text = post.text
    text = text.replace("🔥", "").replace("⚠️", "")  # inline logic instead of helper
    text = unicodedata.normalize("NFC", text)
    for slang, replacement in self.slang_dict.items():
        text = text.replace(slang, replacement)
    addresses = []
    for pattern in self.patterns:                  # nested loops in a single function
        matches = re.findall(pattern, text)
        for match in matches:
            # ... 20 more lines of address processing
            addresses.append(match)
    results = []
    for addr in addresses:
        # ... geocoding inline
        results.append(result)
    return results                                 # no return type, untyped result
```

---

## Backend: Type Hints & Return Types

All public functions must have type hints on parameters and return types.
Use `|` union syntax (Python 3.12). Avoid `Any`.

```python
# --- CORRECT ---
from datetime import date, datetime

async def get_locations(
    self,
    bbox: tuple[float, float, float, float],
    date_from: date | None = None,
    date_to: date | None = None,
    min_confidence: float = 0.0,
) -> list[Location]:
    ...

def calculate_confidence(
    self,
    extraction_score: float,
    geocoder_score: float,
) -> float:
    return (extraction_score * 0.5) + (geocoder_score * 0.5)
```

```python
# --- INCORRECT ---
async def get_locations(self, bbox, date_from=None, date_to=None, min_confidence=0.0):
    # no type hints, no return type
    ...

def calculate_confidence(self, extraction_score, geocoder_score):
    # no type hints, no return type
    return (extraction_score * 0.5) + (geocoder_score * 0.5)
```

---

## Backend: Router → Service → Repository

Routers handle HTTP concerns only. Services hold business logic. No direct DB queries in routers.

```python
# --- CORRECT ---
# Router: thin HTTP adapter
@router.get("", response_model=LocationsResponse)
async def get_locations(
    bbox: str = Query(..., description="min_lng,min_lat,max_lng,max_lat"),
    date_from: date | None = None,
    date_to: date | None = None,
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    service: LocationService = Depends(get_location_service),
) -> LocationsResponse:
    filters = LocationFilter(
        bbox=bbox,
        date_from=date_from,
        date_to=date_to,
        min_confidence=min_confidence,
    )
    return await service.get_locations(filters)


# Service: business logic, no HTTP concepts
class LocationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_locations(self, filters: LocationFilter) -> LocationsResponse:
        bbox = filters.parse_bbox()
        stmt = (
            select(Location)
            .where(func.ST_Within(Location.geometry, func.ST_MakeEnvelope(*bbox, 4326)))
            .where(Location.confidence >= filters.min_confidence)
        )
        if filters.date_from:
            stmt = stmt.where(Location.created_at >= filters.date_from)
        result = await self._session.execute(stmt)
        locations = result.scalars().all()
        logger.info("Fetched locations", extra={"count": len(locations), "bbox": bbox})
        return LocationsResponse.from_models(locations)


# Schema: Pydantic v2 models for validation
class LocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    address: str
    confidence: float
    geo_type: str
    latitude: float
    longitude: float
    created_at: datetime


class LocationsResponse(BaseModel):
    type: str = "FeatureCollection"
    features: list[LocationOut]

    @classmethod
    def from_models(cls, locations: list[Location]) -> "LocationsResponse":
        return cls(features=[LocationOut.model_validate(loc) for loc in locations])
```

```python
# --- INCORRECT ---
@router.get("")
async def get_locations(bbox: str, service=Depends(get_location_service)):
    # missing response_model, missing type hints, missing validation
    return await service.get_locations(bbox)


class LocationService:
    def __init__(self, session):               # no type hint
        self.session = session                 # no underscore prefix for private

    async def get_locations(self, bbox):       # no return type, raw bbox string
        # business logic mixed with raw SQL
        result = await self.session.execute(
            text(f"SELECT * FROM locations WHERE ST_Within(geometry, ST_MakeEnvelope({bbox}, 4326))")
            # string interpolation — SQL injection risk
        )
        return result.fetchall()               # raw rows, no schema validation
```

---

## Backend: Error Handling

Custom exception classes in `app/core/exceptions.py`. Global handler maps to HTTP responses.
Never expose stack traces. Each pipeline stage handles its own errors.

```python
# --- CORRECT ---
# app/core/exceptions.py
class AppError(Exception):
    def __init__(self, message: str, code: str, status: int = 400) -> None:
        self.message = message
        self.code = code
        self.status = status


class LocationNotFoundError(AppError):
    def __init__(self, location_id: int) -> None:
        super().__init__(f"Location {location_id} not found", "LOCATION_NOT_FOUND", 404)


class GeocodingError(AppError):
    def __init__(self, address: str) -> None:
        super().__init__(f"Failed to geocode: {address}", "GEOCODING_FAILED", 502)


# app/api/main.py
@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content={"detail": exc.message, "code": exc.code},
    )
```

```python
# --- INCORRECT ---
@router.get("/{location_id}")
async def get_location(location_id: int):
    try:
        location = await service.get(location_id)
        return location
    except Exception as e:                         # bare Exception catch
        return {"error": str(e)}                   # exposes internals, wrong status code
```

---

## Backend: Logging

Use `logging` module, never `print()`. Logger per module. Always include context.

```python
# --- CORRECT ---
import logging

logger = logging.getLogger(__name__)

async def geocode_address(self, address: str) -> GeocodingResult | None:
    logger.debug("Geocoding address", extra={"address": address})
    result = await self._nominatim.search(address)
    if not result:
        logger.warning("Geocoding returned no results", extra={"address": address})
        return None
    logger.info("Geocoded successfully", extra={"address": address, "lat": result.lat, "lon": result.lon})
    return result
```

```python
# --- INCORRECT ---
async def geocode_address(self, address):
    print(f"Geocoding {address}")                  # print instead of logger
    result = await self._nominatim.search(address)
    if not result:
        print("No results")                        # no context, print
        return None
    print(f"Got result: {result}")                 # no structured logging
    return result
```

---

## Backend: Config via pydantic-settings

All settings via environment. Never hardcode values.

```python
# --- CORRECT ---
# app/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str
    telegram_api_id: int
    telegram_api_hash: str
    jwt_secret: str
    cors_origins: list[str] = ["http://localhost:4200"]
    nominatim_rate_limit: float = 1.0
    pipeline_interval_minutes: int = 60


settings = Settings()
```

```python
# --- INCORRECT ---
DATABASE_URL = "postgresql://user:pass@localhost/db"   # hardcoded credentials
RATE_LIMIT = 1.0                                       # magic number, not configurable
JWT_SECRET = "supersecret123"                          # hardcoded secret
```

---

## Backend: SQLAlchemy 2.x Model

Use `mapped_column`, type-annotated fields, spatial indexes on geometry columns.

```python
# --- CORRECT ---
# app/models/location.py
from sqlalchemy import ForeignKey, Index, String, Float, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from geoalchemy2 import Geometry
from app.models.base import Base


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"))
    address: Mapped[str] = mapped_column(String(500))
    street_name: Mapped[str | None] = mapped_column(String(255))
    confidence: Mapped[float] = mapped_column(Float)
    geo_type: Mapped[str] = mapped_column(String(20))
    geometry: Mapped[str] = mapped_column(Geometry("POINT", srid=4326))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    post: Mapped["Post"] = relationship(back_populates="locations")

    __table_args__ = (
        Index("ix_locations_geometry", "geometry", postgresql_using="gist"),
        Index("ix_locations_confidence", "confidence"),
    )
```

```python
# --- INCORRECT ---
# Old SQLAlchemy 1.x style
class Location(Base):
    __tablename__ = "locations"

    id = Column(Integer, primary_key=True)           # Column() instead of mapped_column()
    post_id = Column(Integer, ForeignKey("posts.id"))
    address = Column(String(500))                    # no type annotation
    confidence = Column(Float)
    geometry = Column(Geometry("POINT", srid=4326))  # no spatial index

    post = relationship("Post", back_populates="locations")  # no Mapped[] type
```
