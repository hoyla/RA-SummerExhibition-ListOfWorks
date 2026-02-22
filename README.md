# Catalogue Tool

A tool for ingesting Royal Academy exhibition catalogue Excel files, applying editorial overrides, and generating clean InDesign Tagged Text exports.

---

## Features

- Excel upload and structured import model
- Deterministic normalisation (price, edition, artwork, medium, honorifics)
- Validation warnings for unparseable values
- Editorial overrides per work (title, artist, price, edition, medium)
- Configurable export component order, separators, and character styles
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
4. Configure export settings (component order, styles, include/exclude)
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
  main.py         # App entry point
frontend/
  index.html
  app.js
  style.css
tests/            # pytest suite (63 tests)
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
