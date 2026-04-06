# Claude Instructions

All project documentation must be written in English.

## Claude-Specific Behavior

- Use available Rules from `.claude/rules/` for coding standards, architecture, pipeline, and error handling
- If a Rule applies, prefer it over repeating guidelines here

## IMPORTANT

1. Before writing any code, describe your approach and wait for approval.
2. If requirements are ambiguous, ask clarifying questions before writing code.
3. After finishing code, list edge cases and suggest test scenarios.
4. If a task requires changes to more than 3 files, stop and break it into smaller tasks.
5. When there's a bug, start by reproducing it with a clear scenario, then fix the root cause.
6. Every time I correct you, reflect on what went wrong and update `docs/lessons.md`.

## Core Principles

- **Simplicity First**: Make every change as simple as possible. Impact minimal code.
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
- **Minimal Impact**: Changes should only touch what's necessary. Avoid introducing bugs.

## Task Management

1. **Plan First**: Write plan to `docs/todo.md` with checkable items
2. **Verify Plan**: Check in before starting implementation
3. **Track Progress**: Mark items complete as you go
4. **Explain Changes**: High-level summary at each step
5. **Document Results**: Add review section to `docs/todo.md`
6. **Capture Lessons**: Update `docs/lessons.md` after corrections

## Project Overview

City safety monitoring system: parses Telegram channel posts about dangerous locations, extracts addresses via NLP, geocodes them, visualizes on an interactive map. MVP target city: Odesa, Ukraine.

## Architecture

Monorepo, two processes, shared PostgreSQL+PostGIS DB:

| Component    | Stack                     | Role                           |
| ------------ | ------------------------- | ------------------------------ |
| **API**      | Python 3.12 / FastAPI     | REST endpoints (read-heavy)    |
| **Worker**   | Python 3.12 / APScheduler | Hourly pipeline (write-heavy)  |
| **Frontend** | Angular 21                | Google Maps + admin panel      |
| **Scripts**  | Python                    | Seed data (OSM), Telegram auth |

No in-process coupling — independent restart/scaling. Docker Compose as single deployment unit.

```
wonthurtmaps/
  backend/app/
    api/            # Public + Admin REST endpoints
    worker/         # Pipeline: fetch -> preprocess -> analyze -> geocode -> normalize
    core/           # Config (pydantic-settings), shared utilities
    models/         # SQLAlchemy 2.x + PostGIS models
    services/       # Business logic (slang dict, street renames, confidence)
  frontend/src/app/
    features/map/   # Public map (Google Maps + markerclusterer + heatmap)
    features/admin/ # Admin panel (dashboard, unresolved, dictionary, log)
    core/           # Services, guards, interceptors
    shared/         # Reusable components
  scripts/          # seed_data.py, osm_extractor.py, telegram_auth.py
  data/seed/        # Generated JSON + static abbreviations.json
  docker/           # Dockerfiles
  docs/             # PRD, MVP design, implementation plan
```

## System Requirements

- **Python 3.12+**
- **Node.js** with npm
- **PostgreSQL 17 + PostGIS**
- **Docker & Docker Compose** (recommended for development)

## Build & Run Commands

### Infrastructure

```bash
docker compose up db              # Dev: only DB in Docker
docker compose up                 # Prod: everything in Docker
```

### Backend

```bash
cd backend
uv sync                           # Install deps
uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --reload  # API
python -m app.worker              # Worker
alembic upgrade head              # Migrations
```

### Frontend

```bash
cd frontend
npm ci
ng serve                          # Dev (proxy -> localhost:8000)
ng build --configuration=production
```

### Seed Data

```bash
python scripts/seed_data.py generate --city odesa
python scripts/seed_data.py load --city odesa    # Idempotent upsert
```

### Code Quality

```bash
# Backend
ruff check --fix . && ruff format .   # Lint + format
mypy app/core/ app/services/          # Type check

# Frontend
ng lint                               # ESLint + Prettier
```

## Key Design Decisions (MVP)

- No tests — manual verification; testing deferred to post-MVP
- LLM-based address extraction via Gemini free tier (15 RPM, Pydantic-validated output); local models deferred
- Google Maps Geocoding API as sole geocoder; local Photon deferred to post-MVP
- APScheduler for scheduling; Celery+Redis deferred (migration-ready)
- Single admin account via JWT; multi-user auth deferred

## Rules (auto-loaded from `.claude/rules/`)

| Rule File           | Scope                                           |
| ------------------- | ----------------------------------------------- |
| `architecture.md`   | Layering, database, security, performance       |
| `code-style.md`     | Python/TypeScript style, Angular, anti-patterns |
| `git-operations.md` | Commits, branches, hooks, PR descriptions       |
| `workflow.md`       | Agent pipeline, data pipeline, bug fixes        |

## Agents (from `.claude/agents/`)

| Agent                   | Model  | Trigger                                                                                    |
| ----------------------- | ------ | ------------------------------------------------------------------------------------------ |
| `business-analyst`      | opus   | Requirements engineering, feature planning, task decomposition, MVP scope evaluation       |
| `ddd-architect`         | opus   | Domain model design, bounded contexts, business logic placement decisions                  |
| `developer`             | sonnet | Full-stack features (FastAPI + Angular), pipeline/worker logic, batch processing           |
| `frontend-angular`      | sonnet | Frontend-only: Angular components, Google Maps, SCSS, signals, responsive design           |
| `dba`                   | sonnet | Schema design, Alembic migrations, query optimization, PostGIS, seed data                  |
| `integration-architect` | sonnet | External APIs (Telegram, Google Maps, Google Gemini, OSM), retry/backoff, webhook handlers |
| `debugger`              | sonnet | Bug investigation, stack traces, error diagnosis, root cause analysis                      |
| `code-reviewer`         | sonnet | Code review, architecture audit, security check, convention compliance (read-only)         |

**Code review workflow:**

- `code-reviewer` agent — on-demand reviews ("review my changes", "check this code")
- `superpowers:requesting-code-review` skill — completion verification before merge/PR
- `superpowers:receiving-code-review` skill — when processing review feedback

**When NOT to use agents:** Simple file reads, grep searches, single-file edits — use tools directly.

## Documentation

- [Product Requirements (PRD)](docs/product-requirements-document.md)
- [MVP Design Document](docs/mvp-design-plan.md)
- [Implementation Plan](docs/implementation-plan.md)
- [Seed Data Pipeline](docs/seed-data-pipeline-design.md)
- [Code Examples](docs/code-examples.md)
- Update files in the docs folder after major addition to the project.
