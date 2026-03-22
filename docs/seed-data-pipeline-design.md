# Seed Data Pipeline — Design Spec

## Overview

Bootstrap script that extracts geographic data from OpenStreetMap for Odesa and loads it into the database. Provides the foundational data (streets, districts, abbreviations, street renames) that the processing pipeline needs for location extraction and fuzzy matching.

**Principle:** Seed script handles only deterministic, OSM-sourced data. Slang discovery, colloquial names, and street rename validation happen at runtime through the processing pipeline + admin panel.

---

## Data Types

| # | Data Type | Source | Storage | Mutable by Admin |
|---|-----------|--------|---------|-----------------|
| 1 | Streets (official names) | OSM Overpass API | In-memory city dictionary (JSON) | No (OSM is source of truth) |
| 2 | Russian street names | OSM `name:ru` + rule-based generation | Same JSON as streets | No |
| 3 | Districts (polygons) | OSM Overpass API | `districts` table | No |
| 4 | Street renames (old → new) | OSM `old_name` tags | `street_renames` table, `status=pending` | Yes — admin validates before activation |
| 5 | Abbreviations | Static JSON, hand-written | In-memory config | No (developer updates) |

**Not in seed (handled by runtime system):**
- Slang dictionary — discovered by pipeline, managed by admin
- Colloquial names — same as slang
- POI / landmarks — out of MVP scope

---

## Pipeline Steps

### Step 1: OSM Street Extraction

**Overpass API query** for Odesa bbox (`46.35,30.60,46.55,30.85`):
- All `way[highway]` and `relation[type=street]` with `name` tag
- Extract: `name` (uk), `name:ru`, `old_name`, `old_name:ru`, node coordinates
- Compute centroid per street (average of all node coordinates across all way segments with the same name)
- Deduplicate by name — one street may have multiple `way` segments; merge all node coordinates and `osm_ids` before computing centroid

**Output `data/seed/streets.json`:**
```json
{
  "streets": [
    {
      "name_uk": "Дерибасівська вулиця",
      "name_ru": "Дерибасовская улица",
      "name_ru_source": "osm",
      "centroid_lat": 46.4856,
      "centroid_lng": 30.7406,
      "osm_ids": [12345, 67890]
    }
  ]
}
```

### Step 2: Russian Name Generation

For streets where OSM lacks `name:ru`, apply rule-based Ukrainian → Russian transformation:

**Rules:**
- "вулиця" → "улица"
- "провулок" → "переулок"
- "площа" → "площадь"
- "бульвар" → "бульвар" (no change)
- "проспект" → "проспект" (no change)
- Proper name morphology (common suffix patterns)

Records generated this way are marked with `"name_ru_source": "rules"` for transparency.

**Limitation:** Rule-based transformation won't be 100% accurate for all proper names. This is acceptable — the primary matching happens against official OSM names, and Russian variants are a fuzzy matching aid.

### Step 3: District Extraction

**Overpass API query:**
- `relation[boundary=administrative]` within bbox
- `relation[place=suburb]`, `relation[place=quarter]`, and `relation[place=neighbourhood]` within bbox
- Also check `way` elements with same tags (some microdistricts mapped as ways, not relations)

**Extract:** `name`, `name:ru`, polygon geometry.

**Output `data/seed/districts.json`:**
```json
{
  "districts": [
    {
      "name_uk": "Аркадія",
      "name_ru": "Аркадия",
      "polygon": [[46.42, 30.74], [46.43, 30.75], ...]
    }
  ]
}
```

**Known limitation:** Some microdistricts (Таїрова, Черьомушки) may not have polygons in OSM. These will be missing from seed data — admin can flag this as a gap, and polygons can be added manually later.

### Step 4: Street Renames Extraction

Extracted from OSM `old_name` / `old_name:ru` tags during Step 1 (same Overpass query).

**Output `data/seed/street_renames.json`:**
```json
{
  "renames": [
    {
      "old_name_uk": "вулиця Жуковського",
      "old_name_ru": "улица Жуковского",
      "new_name_uk": "вулиця Святослава Караванського",
      "new_name_ru": "улица Святослава Караванского",
      "year_renamed": null
    }
  ]
}
```

**All renames loaded with `status=pending`.** Admin validates each rename before the system starts using it. This prevents OSM data errors from silently corrupting geocoding results.

### Step 5: Abbreviations (Static)

Hand-written file, committed to git. No generation needed.

**`data/seed/abbreviations.json`:**
```json
{
  "abbreviations": [
    {"abbr": "вул.", "full_uk": "вулиця", "full_ru": "улица"},
    {"abbr": "пр.", "full_uk": "проспект", "full_ru": "проспект"},
    {"abbr": "бульв.", "full_uk": "бульвар", "full_ru": "бульвар"},
    {"abbr": "пл.", "full_uk": "площа", "full_ru": "площадь"},
    {"abbr": "пров.", "full_uk": "провулок", "full_ru": "переулок"},
    {"abbr": "ген.", "full_uk": "генерала", "full_ru": "генерала"},
    {"abbr": "акад.", "full_uk": "академіка", "full_ru": "академика"},
    {"abbr": "р-н", "full_uk": "район", "full_ru": "район"},
    {"abbr": "м-н", "full_uk": "мікрорайон", "full_ru": "микрорайон"},
    {"abbr": "ст.", "full_uk": "станція", "full_ru": "станция"}
  ]
}
```

---

## Script Structure

```
scripts/
  seed_data.py          — main script, orchestrates all steps
  osm_extractor.py      — Overpass API queries + parsing
  ru_name_generator.py  — rule-based uk → ru transformation

data/
  seed/
    streets.json        — generated by script
    districts.json      — generated by script
    street_renames.json — generated by script
    abbreviations.json  — static, committed to git
```

## CLI Interface

```bash
# Step 1: Extract data from OSM + generate Russian names
python scripts/seed_data.py generate --city odesa

# Step 2: Review generated files (optional manual check)

# Step 3: Load into database (city must exist in `cities` table)
python scripts/seed_data.py load --city odesa
```

`--city` defaults to `odesa`. The target city must already exist in the `cities` table (created by initial DB migration with seed data for Odesa).

## Idempotency

`load` command uses upsert (INSERT ON CONFLICT UPDATE). Safe to re-run:
- New streets/districts are added
- Existing records are updated with latest OSM data
- Admin-modified records (e.g., validated renames) are NOT overwritten — `status` field is preserved for records already in DB

---

## Admin Panel Additions

### Processing Log (new feature)

Admin sees a feed of all processed posts with the system's decision chain:

```
Post: "на жуковского возле парка стрельба"
  → Recognized street: "вулиця Жуковського"
  → Rename applied: "Жуковського" → "Святослава Караванського" [pending]
  → Map point: [46.484, 30.739]
  → Confidence: 0.72

  [Correct] [Edit] [Wrong]
```

This extends the existing `AdminUnresolvedComponent` concept to cover **all processed posts**, not just unresolved ones. Filterable by status, confidence, date.

Admin can:
- See the full decision chain (extraction → rename → geocode)
- Validate or reject specific rename mappings
- Correct wrong location bindings

### Street Renames Validation

Renames from seed enter as `status=pending`. Admin activates them through the admin panel. This prevents OSM data errors from silently affecting geocoding.

---

## Runtime Discovery (existing system design, not part of seed)

Slang and colloquial names are discovered organically:

```
Message "на дерибоне біля аптеки"
    → pipeline can't find "дерибон" in street dictionary
    → saves as unrecognized_token
    → admin sees "дерибон" (10 occurrences)
    → admin maps to "Дерибасівська вулиця"
    → slang_dictionary entry created, status=active
    → future messages with "дерибон" resolve automatically
```

This leverages the self-learning workflow already defined in the MVP Design Document.

---

## Error Handling

### Overpass API
- Retry with exponential backoff (3 attempts, 5s/15s/45s delays)
- Timeout per query: 60 seconds
- If query returns partial results: warn in console, proceed with what was received
- If Overpass is completely unavailable: abort with clear error message, user retries manually

### Bbox Over-Inclusion
The bbox `46.35,30.60,46.55,30.85` may include streets from neighboring settlements. This is acceptable — extra streets in the dictionary don't cause false positives (fuzzy matching still requires context from the post text). No filtering needed for MVP.

---

## Schema Updates Required

The `street_renames` table in the MVP Design Document needs two additions to support this pipeline:
- Bilingual columns: `old_name_uk`, `old_name_ru`, `new_name_uk`, `new_name_ru` (replacing single `old_name`/`new_name`)
- `status` enum: `pending`, `active`, `rejected` (admin validates before system uses the rename)
