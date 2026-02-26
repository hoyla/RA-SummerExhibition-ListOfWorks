# Developer guide

Operational reference for working on the Catalogue Tool. For architecture
details see [architecture_v1.md](architecture_v1.md).

---

## Project overview

The **Catalogue Tool** produces InDesign-ready Tagged Text for the Royal
Academy Summer Exhibition catalogue. It handles two products:

1. **List of Works (LoW)** — artwork entries with artist, title, price, etc.
2. **Artists' Index** — alphabetical artist listing with catalogue numbers.

### Tech stack

| Layer    | Technology                                      |
| -------- | ----------------------------------------------- |
| Backend  | Python 3.12, FastAPI, SQLAlchemy, Alembic       |
| Database | PostgreSQL 16 (Docker), SQLite (tests)          |
| Frontend | Vanilla JS SPA (`frontend/app.js`, ~4500 lines) |
| Infra    | Docker Compose (local), ECS Fargate (staging/prod) |

### Key directories

| Path                          | Purpose                                          |
| ----------------------------- | ------------------------------------------------ |
| `backend/app/api/`            | FastAPI route modules and Pydantic schemas        |
| `backend/app/models/`         | SQLAlchemy ORM models                            |
| `backend/app/services/`       | Business logic (import, normalise, resolve, export) |
| `backend/alembic/versions/`   | Database migrations (auto-run on startup)        |
| `backend/seed_templates/`     | Default templates and known artist seed data     |
| `frontend/`                   | Single-page app (`app.js`, `style.css`, `index.html`) |
| `tests/`                      | Pytest suite (~711 tests, SQLite in-memory)      |

### Data flow

```
Spreadsheet upload → Parse & normalise → Store raw + normalised
  → Known Artist lookup → User overrides → Resolved output → Export
```

### Three-layer override resolution (Artists' Index)

Values resolve left-to-right; first non-null wins:

1. **User override** (`IndexArtistOverride`) — highest priority
2. **Known Artist** (`KnownArtist`) — pre-configured corrections
3. **Normalised** (from importer heuristics) — lowest priority

Convention: `""` (empty string) = "clear this field to blank";
`None`/`null` = "no override, fall through to next layer".

### Validation warnings

The importer emits warnings in two categories, shown in the UI with distinct
badge colours:

**Changed (blue `badge-info`)** — normalisation engine modified data:
- `whitespace_trimmed`, `multi_artist_name_changed`, `quals_extracted`,
  `ra_member_detected`, `possible_company`, `duplicate_name_merged`

**Suspected (amber `badge-warning`)** — may need human review:
- `multi_artist_name_suspected`, `ra_styling_ambiguous`, `quals_in_name_field`,
  `non_ascii_characters`, `missing_cat_nos`, `duplicate_filename`,
  `empty_spreadsheet`, `missing_column`

Warning types are free-text strings in the `ValidationWarning` table — no
enum or migration is needed to add new types.

### Frontend detail table

When clicking an artist entry, the detail table shows the data pipeline:

| Column          | Shows                                                       |
| --------------- | ----------------------------------------------------------- |
| Field           | Field name (including derived fields like Artist 2, RA Styled) |
| Spreadsheet     | Raw value from the Excel file (dash for derived fields)     |
| Resolved        | After normalisation + known artist lookup                   |
| Manual Override  | After user overrides (only shown when overrides exist)      |

Values are styled: **grey** = unchanged from previous column,
**bold black** = changed by this stage.

---

## Local development

Local development uses **Docker Compose** — the app runs inside a container
alongside a PostgreSQL 16 instance.

### First-time setup

```bash
cp .env.example .env          # edit if you want different passwords
docker compose up -d           # starts both db and app containers
open http://localhost:8000/ui   # UI is served by the app container
```

### Day-to-day commands

| Task                         | Command                                         |
| ---------------------------- | ----------------------------------------------- |
| Start the app                | `docker compose up -d app`                      |
| Rebuild after code changes   | `docker compose up -d --build app`              |
| View logs                    | `docker compose logs app --tail=50`             |
| Follow logs live             | `docker compose logs app -f`                    |
| Stop everything              | `docker compose down`                           |
| Stop and **delete all data** | `docker compose down -v` (removes DB + uploads) |

### Important notes

- **Never run `python backend/app/main.py` directly** — the app requires the
  Dockerised PostgreSQL and the container's `UPLOAD_DIR` setup.
- Uploaded files are stored in a **Docker named volume** (`uploads`), not in the
  workspace `uploads/` folder. They persist across rebuilds but are deleted by
  `docker compose down -v`.
- Database data is in a named volume (`pgdata`), same lifecycle.
- Alembic migrations run **automatically on container startup** — no manual
  `alembic upgrade head` needed.
- The local environment has **no authentication** by default (no Cognito, no
  API key). The UI shows an "admin" role with full access.

> **⚠️ `.env` gotcha**: If `.env` has `API_KEY=some-value`, the app enters
> API-key mode and all requests (including tests) need that key. For local
> dev you usually want `API_KEY=` (empty) so no-auth mode is active.

---

## Running tests

Tests run against an **in-memory SQLite database** — no Docker required.

```bash
# One-time: create venv and install dependencies
python -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt

# Run all tests (~711)
python -m pytest tests/ -q

# Run a single test file
python -m pytest tests/test_normalisation.py -q

# Run with verbose output
python -m pytest tests/ -v

# Stop on first failure
python -m pytest tests/ -x
```

If you see `ModuleNotFoundError` when running tests, re-run:

```bash
pip install -r requirements-dev.txt
```

---

## Database migrations (Alembic)

### When to create a migration

**Every time you add, remove, or change a column in a SQLAlchemy model**, you
must create a corresponding Alembic migration. The model change alone does NOT
alter the database.

> **⚠️ Tests will NOT catch a missing migration.** The test suite uses SQLite
> with `Base.metadata.create_all()`, which builds tables directly from your
> models — Alembic is never involved. A column can exist in the model (all
> tests pass) but be completely absent from the real PostgreSQL database,
> causing a silent 500 in production. Always verify against Docker.

Checklist:

1. Edit the model in `backend/app/models/`
2. Create a new migration file in `backend/alembic/versions/`
3. **Rebuild Docker**: `docker compose up -d --build app` (migration runs on startup)
4. **Check logs**: `docker compose logs app --tail=20` — look for
   `Running upgrade ... → ...`
5. **Hit the affected endpoint** with `curl` or the UI to confirm it works
   against real PostgreSQL (don't rely on tests alone)
6. Run tests: `python -m pytest tests/ -x -q`

If you change multiple related tables (e.g. `index_artists` and
`index_artist_overrides`), make sure **both** get migrations — it's easy to
forget the secondary table.

### Migration file template

```python
"""Short description of what changed

Revision ID: <unique_hex_id>
Revises: <previous_revision_id>
Create Date: YYYY-MM-DD
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "<unique_hex_id>"
down_revision: Union[str, Sequence[str], None] = "<previous_revision_id>"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column("table_name", sa.Column("new_col", sa.Text(), nullable=True))

def downgrade() -> None:
    op.drop_column("table_name", "new_col")
```

The `down_revision` must point to the **latest existing** migration. Check with:

```bash
# Show current head(s) — must be exactly one
alembic heads

# If you see multiple heads, your new migration's down_revision is wrong.
# It should point to the single current head, not an older revision.

# List all migration files
ls backend/alembic/versions/ | sort
```

> **⚠️ Multiple heads = broken chain.** If `alembic heads` shows more than
> one head, a migration has been pointed at a stale `down_revision`. This
> causes `alembic upgrade head` to fail on container startup. Fix it by
> changing the new migration's `down_revision` to the correct parent.
> Always run `alembic heads` after creating a migration to verify.

### How migrations run

- **Locally**: automatically on Docker container startup (`main.py` calls
  `alembic upgrade head`)
- **Staging/Prod**: automatically when the new ECS task starts after CI/CD
  deploy

---

## Environments

| Environment    | URL                        | Database                  | File storage                 | Deployed by                 |
| -------------- | -------------------------- | ------------------------- | ---------------------------- | --------------------------- |
| **Local**      | `localhost:8000`           | Docker PostgreSQL         | Docker volume (`uploads`)    | `docker compose up`         |
| **Staging**    | `staging-catalogue.hoy.la` | RDS (`catalogue-staging`) | S3 (`catalogue-staging-...`) | Push to any non-main branch |
| **Production** | `catalogue.hoy.la`         | RDS (`catalogue-prod`)    | S3 (`catalogue-prod-...`)    | Push/merge to `main`        |

### CI/CD pipeline (GitHub Actions)

Every push triggers:

1. **Test** — runs `pytest` against the full test suite
2. **Build** — builds Docker image, pushes to ECR
3. **Deploy staging** — updates ECS service `catalogue-staging` (non-main branches)
4. **Deploy production** — updates ECS service `catalogue-prod` (main branch only)

AWS resources use **per-environment secrets** in AWS Secrets Manager:

- `catalogue-staging/DATABASE_URL`, `catalogue-staging/API_KEY`, `catalogue-staging/S3_BUCKET`
- `catalogue-prod/DATABASE_URL`, `catalogue-prod/API_KEY`, `catalogue-prod/S3_BUCKET`

---

## Error handling and logging architecture

The app uses structured JSON logging via a custom formatter on the root
Python logger. All application code logs through `logging.getLogger("catalogue")`.

### How errors flow through the stack

FastAPI/Starlette wraps requests in several layers. Understanding the order
matters when debugging silent failures:

```
Request → ServerErrorMiddleware → CORS → _log_requests → _set_user_context → Route handler → Response
```

| Error type                                   | Where it happens                                                 | How it's handled                                             | Visible in logs?                                      |
| -------------------------------------------- | ---------------------------------------------------------------- | ------------------------------------------------------------ | ----------------------------------------------------- |
| **HTTPException** (4xx)                      | Route handler raises it                                          | FastAPI returns JSON error                                   | ✅ Yes — `_log_requests` sees the status code         |
| **RequestValidationError** (422)             | Before route handler — bad input                                 | FastAPI returns 422 with details                             | ✅ Yes                                                |
| **Unhandled exception** in route             | Inside route handler                                             | `ServerErrorMiddleware` catches, logs traceback, returns 500 | ✅ Yes — routed through `uvicorn.error` → root logger |
| **ResponseValidationError**                  | During response body serialization (after `call_next()` returns) | Custom `@app.exception_handler` logs and returns JSON 500    | ✅ Yes (since Feb 2026 fix)                           |
| **DB schema mismatch** (e.g. missing column) | SQLAlchemy query execution                                       | Falls into unhandled exception path                          | ✅ Yes (if uvicorn logger is configured correctly)    |

### Key implementation details

- `_setup_logging()` in `main.py` forces all uvicorn loggers (`uvicorn`,
  `uvicorn.error`, `uvicorn.access`) to propagate to the root logger with our
  JSON formatter. Without this, Starlette's `ServerErrorMiddleware` tracebacks
  would be silently lost.
- The `ResponseValidationError` handler was added because this error type
  bypasses all middleware — it occurs during response body streaming, after
  `call_next()` has already returned a `Response` object.
- If you ever see a 500 with `content-type: text/plain` and body
  "Internal Server Error" but **nothing in the logs**, something has broken
  the logger pipeline. Check that `_setup_logging()` still clears and
  re-attaches uvicorn's loggers.

### Application error handling

- **LoW upload errors** are caught and returned as 400 responses.
- **Index upload errors** are caught and logged; `IndexImportError` → 400,
  other exceptions → 500 with detail logged to stdout.

### Debugging a silent 500

If an endpoint returns 500 with no log output:

1. Check `docker compose logs app` for **any** recent output
2. Try exec'ing into the container and calling the function directly:
   ```bash
   docker compose exec -T app python3 -c '
   from backend.app.db import SessionLocal
   # ... call the function that 500s and print the traceback
   '
   ```
3. Check whether the DB schema matches the model:
   ```bash
   docker compose exec db psql -U catalogue -d catalogue -c "
     SELECT column_name FROM information_schema.columns
     WHERE table_name = '...' ORDER BY ordinal_position"
   ```

---

## Key conventions

- **Raw data is immutable** — the raw columns on Import/Work/IndexArtist are
  never modified after import.
- **Normalisation is deterministic** — same input always produces same output.
- **Overrides are separate** — editorial changes are stored in override tables,
  never patched into the raw or normalised layer.
- **Seed templates** — JSON files in `backend/seed_templates/` are upserted on
  startup. The app compares config hashes and only writes when content changes.
- **Tests use SQLite** — the test suite runs entirely in-memory with no external
  dependencies.

---

## Common pitfalls

| Mistake                                          | Prevention                                                                                                                           |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------ |
| Changed a model but forgot the Alembic migration | Always create a migration when changing model columns. **Tests won't catch this** — they use SQLite with `create_all()`, not Alembic |
| Changed one table but forgot a related table     | If you add columns to `index_artists`, check whether `index_artist_overrides` also needs updating (and vice versa)                   |
| Ran the app with `python` instead of Docker      | Use `docker compose up -d --build app`                                                                                               |
| Tests fail with `ModuleNotFoundError`            | Run `pip install -r requirements-dev.txt`                                                                                            |
| Endpoint returns 500 but nothing in logs         | See "Debugging a silent 500" above. Most likely a missing migration or a ResponseValidationError                                     |
| Tests pass but endpoint 500s on Docker           | The DB schema is out of sync with the model — a migration is missing. Compare `information_schema.columns` with the model            |
| `docker compose down -v` deleted my test data    | Only use `-v` when you want a fresh start                                                                                            |
| Staging not updating after push                  | Check the GitHub Actions run completed successfully                                                                                  |
| Tests all fail with 401/403                      | `.env` has `API_KEY=some-value` — clear it to `API_KEY=` for no-auth mode                                                            |
| Warning type not showing in UI                   | Warning types are free-text — no migration needed. Check the label map `_IDX_WARNING_LABELS` in `app.js` and the `_IDX_CHANGED_TYPES` set |
