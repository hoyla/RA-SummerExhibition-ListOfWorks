# Royal Academy Summer Exhibition catalogue tool

The Royal Academy's annual Summer Exhibition features a printed catalogue.
The editorial team prepares exhibition data in Excel spreadsheets. This tool
ingests those spreadsheets, lets editors review and correct the data, and
generates InDesign Tagged Text files ready for import into the catalogue
layouts. It replaces a manual copy-and-format workflow that involved hundreds
of time-consuming and error-prone regex and find-and-replace operations.

Supports two data products:

- **List of Works** — the main exhibition catalogue (sections → works)
- **Artists Index** — alphabetical index of exhibiting artists with catalogue numbers

---

## Features

### List of Works

- Excel upload and structured import model (Import → Section → Work)
- Deterministic normalisation (price, edition, artwork, medium, honorifics)
- Configurable normalisation config (honorific token list)
- Validation warnings for unparseable values
- Editorial overrides per work (title, artist, price, edition, medium)
- Export templates: named, versioned configs stored in the database
- Configurable export component order, separators, balance-lines, and character styles
- Per-component include/exclude toggle
- Section-level exports with custom filenames
- Re-import with override preservation
- Export diff (compare current output to last snapshot)

### Artists Index

- Excel upload with automatic artist parsing and normalisation
- RA member detection from qualifications
- Multi-name and multi-artist parsing (e.g. "Boyd & Evans")
- Company vs individual detection
- Sort key generation and alphabetical grouping
- Editorial overrides per artist (name, title, quals, company, address, RA styling, include)
- Known Artists lookup with pre-baked title, company, and address fields
- Seed data for Known Artists (JSON), seeded entries read-only with duplicate-to-edit
- Export templates with configurable paragraph/character styles
- Section separator between letter groups (paragraph, column break, etc.)
- Per-letter collapsible preview with individual letter export
- Validation warnings with filterable badge summary

### Shared

- Built-in seed templates (upserted from `backend/seed_templates/*.json` on startup)
- InDesign Tagged Text export (ASCII-MAC encoding, Mac Roman)
- JSON export
- Per-user authentication via **AWS Cognito** (JWT), with API key fallback
- Three-tier role model: Viewer / Editor / Admin (mapped from Cognito groups)
- In-app user management panel for admins (create, role change, enable/disable, password reset)
- Audit logging for all mutating operations with user attribution
- Full frontend UI (vanilla JS SPA)
- AWS deployment: ECS Fargate, RDS PostgreSQL, S3, ALB with HTTPS
- CI/CD via GitHub Actions (branch-based: working branches → staging, main → production)

---

## Tech stack

- Python 3.12 / FastAPI / Uvicorn
- SQLAlchemy 2.0 + PostgreSQL 16 (RDS in production)
- Pydantic v2
- AWS Cognito (authentication) + boto3 (user management)
- Vanilla JS single-page frontend
- Docker / ECS Fargate / GitHub Actions CI/CD

---

## Quick start (Docker)

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

## Typical workflow

### List of Works

1. Upload an Excel file via the UI (or `POST /import`)
2. Browse sections and works; check normalisation warnings
3. Apply overrides where needed (title, artist, price, edition, medium)
4. Select or create an export template (Templates page)
5. Export the full import or a single section as InDesign Tagged Text

### Artists Index

1. Upload an Index Excel file via the Artists' Index tab
2. Review artist entries grouped by letter; check warnings and flags
3. Apply overrides where needed (name, quals, company toggle)
4. Select or create an Index export template
5. Export the full index or individual letter groups

---

## Project structure

```
backend/app/
  api/            # FastAPI route handlers
    index.py      # Artists' Index routes
    index_templates.py
    low_imports.py    # List of Works routes
    low_overrides.py
    low_exports.py
    low_templates.py
    known_artists.py
    users.py      # Cognito user management (admin-only)
    auth.py       # Authentication (Cognito JWT / API key / no-auth)
    user_context.py # Request-scoped user context
    schemas.py    # Centralised Pydantic models
  models/         # SQLAlchemy ORM models
  services/       # Business logic
    excel_importer.py
    normalisation_service.py
    override_service.py
    export_renderer.py       # LoW renderer
    index_importer.py        # Index importer
    index_renderer.py        # Index renderer
    index_override_service.py
    export_diff_service.py
  config.py       # App settings
  db.py           # Database session
  main.py         # App entry point + seed template loader
backend/seed_templates/
                  # Built-in template + known artist JSON files
frontend/
  index.html
  app.js
  style.css
tests/            # pytest suite (700 tests across 28 test files)
.github/workflows/
  ci.yml          # GitHub Actions CI/CD pipeline
.aws/
  task-definition-staging.json  # ECS task definition (staging)
  task-definition-prod.json     # ECS task definition (production)
docs/
  architecture_v1.md
  dev-guide.md      # Developer guide (local setup, migrations, environments)
  export_spec_v1.md
  roadmap.md
```

---

## Running tests

```bash
python -m pytest tests/ -q
```

---

## Database migrations

This project uses Alembic for database migrations.

- On startup, `alembic upgrade head` runs automatically.
- Existing databases without an `alembic_version` table are auto-stamped at the
  baseline revision before upgrading.
- Schema changes should be added as new Alembic revisions.

---

## Environment variables

| Variable               | Default                   | Description                                         |
| ---------------------- | ------------------------- | --------------------------------------------------- |
| `DATABASE_URL`         | —                         | PostgreSQL connection string                        |
| `POSTGRES_PASSWORD`    | `changeme`                | Used by docker-compose                              |
| `COGNITO_USER_POOL_ID` | _(empty)_                 | Cognito User Pool ID (enables JWT auth)             |
| `COGNITO_CLIENT_ID`    | _(empty)_                 | Cognito App Client ID                               |
| `COGNITO_REGION`       | `eu-north-1`              | AWS region for Cognito                              |
| `API_KEY`              | _(empty — auth disabled)_ | Legacy shared API key (ignored when Cognito is set) |
| `STORAGE_BACKEND`      | `local`                   | File storage: `local` or `s3`                       |
| `S3_BUCKET`            | _(empty)_                 | S3 bucket name (when `STORAGE_BACKEND=s3`)          |
| `AWS_REGION`           | —                         | AWS region for S3 and other services                |
| `LOG_LEVEL`            | `INFO`                    | Uvicorn log level                                   |
| `CORS_ORIGINS`         | _(empty — disabled)_      | Comma-separated allowed origins for CORS            |
| `UPLOAD_DIR`           | `uploads`                 | Local directory for uploaded files                  |

---

## Philosophy

- Raw data is preserved and never mutated
- Normalisation is deterministic and idempotent
- Export rules are separate from parsing logic
- Structure over presentation
