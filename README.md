# Catalogue Tool

A tool for ingesting Royal Academy exhibition catalogue Excel files, applying editorial overrides, and generating clean InDesign Tagged Text exports.

---

## Features

- Excel upload and structured import model
- Deterministic normalisation (price, edition, artwork, medium, honorifics)
- Configurable normalisation config (honorific token list)
- Validation warnings for unparseable values
- Editorial overrides per work (title, artist, price, edition, medium)
- Export templates: named, versioned configs stored in the database
- Built-in seed templates (upserted from `backend/seed_templates/*.json` on startup)
- Configurable export component order, separators, balance-lines, and character styles
- Per-component include/exclude toggle
- InDesign Tagged Text export (ASCII-MAC encoding)
- JSON export
- Section-level exports
- API key authentication
- Full frontend UI

---

## Tech Stack

- Python 3.12 / FastAPI / Uvicorn
- SQLAlchemy + PostgreSQL 16
- Pydantic v2
- Vanilla JS single-page frontend
- Docker / docker-compose

---

## Quick Start (Docker)

```bash
# Copy env template and set a password / API key
cp .env.example .env

# Build and start
docker compose up --build -d

# Open the UI
open http://localhost:8000/ui
```

The database is created automatically on first start.

### Local development (without Docker)

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

export DATABASE_URL=postgresql://catalogue:changeme@localhost:5432/catalogue
uvicorn backend.app.main:app --reload
```

---

## Typical Workflow

1. Upload an Excel file via the UI (or `POST /api/imports`)
2. Browse sections and works; check normalisation warnings
3. Apply overrides where needed (title, artist, price, edition, medium)
4. Select or create an export template (Templates page)
5. Export the full import or a single section as InDesign Tagged Text

---

## Project Structure

```
backend/app/
  api/            # FastAPI route handlers
  models/         # SQLAlchemy ORM models
  services/       # Business logic (import, normalisation, export, overrides)
  config.py       # App settings
  db.py           # Database session
  main.py         # App entry point + seed template loader
backend/seed_templates/
                  # Built-in template JSON files (upserted on startup)
frontend/
  index.html
  app.js
  style.css
tests/            # pytest suite (114 tests)
docs/
  architecture_v1.md
  export_spec_v1.md
  roadmap.md
```

---

## Running Tests

```bash
venv/bin/python -m pytest tests/ -q
```

---

## Database Migrations

This project uses SQLAlchemy's `create_all` rather than Alembic. New tables are
created automatically on startup, but **new columns added to existing tables
require a manual `ALTER TABLE`**.

If you pull an update that adds a column, run the corresponding command against
your running database before or after restarting the app. Example:

```bash
docker compose exec db psql -U catalogue -d catalogue -c \
  "ALTER TABLE works ADD COLUMN IF NOT EXISTS my_column TEXT;"
```

### Backfilling computed columns

When a new normalised column is added, existing rows won't have it populated
until re-imported. You can backfill directly from the raw column instead:

```bash
# Example: backfill artwork from raw_artwork
docker compose exec db psql -U catalogue -d catalogue -c \
  "UPDATE works SET artwork = raw_artwork::integer WHERE raw_artwork ~ '^\d+$';"
```

The general pattern is: cast the raw value to the target type where it parses
cleanly; rows with unparseable values stay `NULL`, which is correct.

---

## Environment Variables

| Variable            | Default                   | Description                               |
| ------------------- | ------------------------- | ----------------------------------------- |
| `DATABASE_URL`      | —                         | PostgreSQL connection string              |
| `POSTGRES_PASSWORD` | `changeme`                | Used by docker-compose                    |
| `API_KEY`           | _(empty — auth disabled)_ | Bearer token required on all API requests |
| `LOG_LEVEL`         | `INFO`                    | Uvicorn log level                         |

---

## Philosophy

- Raw data is preserved and never mutated
- Normalisation is deterministic and idempotent
- Export rules are separate from parsing logic
- Structure over presentation
