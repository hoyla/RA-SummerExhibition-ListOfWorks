# Catalogue Tool – Architecture

## 1. System Overview

The Catalogue Tool ingests Royal Academy exhibition catalogue Excel files,
applies editorial overrides, and generates InDesign-ready Tagged Text exports.

Data flow:

```
Excel Upload
  → Import Record (immutable)
  → Sections
  → Works (raw + normalised fields)
  → [Editorial Overrides]
  → Export Layer  →  InDesign Tagged Text / JSON
```

---

## 2. Technology Stack

| Layer      | Technology                        |
| ---------- | --------------------------------- |
| API        | Python 3.12, FastAPI, Uvicorn     |
| ORM        | SQLAlchemy 2.0                    |
| Migrations | Alembic                           |
| Validation | Pydantic v2                       |
| Database   | PostgreSQL 16                     |
| Frontend   | Vanilla JS SPA, served by FastAPI |
| Deployment | Docker / docker-compose           |
| Testing    | pytest (172 tests)                |

---

## 3. Data Model

### Import

One uploaded Excel file. Immutable after creation.

- `id` (UUID), `filename`, `uploaded_at`, `notes`

### Section

A gallery room within an import. Ordered by `(import_id, position)`.

- `id`, `import_id`, `name`, `position`

### Work

One catalogue entry. Ordered by `(section_id, position_in_section)`.

**Raw fields** (preserved verbatim from Excel):

- `raw_cat_no`, `raw_title`, `raw_artist`, `raw_price`, `raw_edition`, `raw_artwork`, `raw_medium`

**Normalised fields** (computed by normalisation service):

- `title`, `artist_name`, `artist_honorifics`
- `price_numeric`, `price_text`
- `edition_total`, `edition_price_numeric`
- `artwork` (integer — number of pieces)
- `medium`
- `include_in_export` (boolean)

### WorkOverride

Optional editorial corrections for a single work. `None` means "use Work value".

- `title_override`, `artist_name_override`, `artist_honorifics_override`
- `price_numeric_override`, `price_text_override`
- `edition_total_override`, `edition_price_numeric_override`
- `medium_override`

### ValidationWarning

Recorded when a raw field cannot be parsed to its expected type.

- `import_id`, `work_id`, `field`, `raw_value`, `message`

### AuditLog

Records all mutating API calls for traceability.

### Ruleset

Stores both export templates and global normalisation config in a single table,
distinguished by `config_type` (`'template'` | `'normalisation'`).

- `id` (UUID), `name`, `config` (JSONB), `config_hash`, `config_type`
- `is_builtin` — `True` for seed templates shipped with the repository
- `slug` — short identifier used for seed deduplication (e.g. `ra-default`)
- `archived` — soft-delete flag
- `created_at`

Built-in templates are seeded from `backend/seed_templates/*.json` on startup
and upserted (name + config updated) whenever the file's hash has changed.

---

## 4. Normalisation Layer

`backend/app/services/normalisation_service.py`

- **Price**: strips currency symbols, parses decimals; passes through `NFS`, `_`, blank
- **Edition**: parses `X` or `X at £Y` patterns; edition of 0 is suppressed in export
- **Artwork**: parses integer number of pieces from `raw_artwork`
- **Medium**: trimmed, passed through as-is
- **Honorifics**: split from artist name using known suffix list (RA, Hon RA, etc.)

Principles: deterministic, idempotent, raw data never mutated.

---

## 4.1 Spreadsheet Validation

`backend/app/services/excel_importer.py`

Before importing, the header row is validated:

- **Required columns** (`Cat No`, `Title`, `Artist`) — missing any → 400 error
  with a "did you mean?" suggestion when a close match exists.
- **Optional columns** (`Gallery`, `Price`, `Edition`, `Artwork`, `Medium`) —
  missing → import proceeds but a `missing_column` validation warning is stored.
- **Non-Excel files** and corrupt/empty spreadsheets → 400 with a clear message.
- **Header-only spreadsheets** → import succeeds with an `empty_spreadsheet` warning.

---

## 5. Override Service

`backend/app/services/override_service.py`

`resolve_effective_work(work, override) → EffectiveWork`

Merges a Work ORM object with an optional WorkOverride. Each field prefers the
override value if set, otherwise falls back to the normalised Work value.
Returns an `EffectiveWork` dataclass used by the export renderer.

---

## 6. Export Layer

`backend/app/services/export_renderer.py`

### InDesign Tagged Text

- Header: `<ASCII-MAC>`
- Encoding: Mac Roman bytes; characters outside Mac Roman encoded as `<0x####>`
- Line endings: CR (`\r`)
- Paragraph styles: `<ParaStyle:Name>`
- Character styles: `<CharStyle:Name>...<CharStyle:>` (empty tag resets to default)

### ExportConfig

Controls all export behaviour:

- `currency_symbol`, `thousands_separator`, `decimal_places`
- `section_style`, `entry_style` — InDesign paragraph style names
- `cat_no_style`, `artist_style`, `honorifics_style`, `title_style`, `price_style`, `medium_style`, `artwork_style` — character style names
- `honorifics_lowercase`
- `leading_separator`, `trailing_separator`
- `components` — ordered list of `ComponentConfig`

### ComponentConfig

Each component in the entry layout:

- `field` — one of: `work_number`, `artist`, `title`, `edition`, `artwork`, `price`, `medium`
- `separator_after` — `none`, `space`, `tab`, `right_tab`, `soft_return`, `hard_return`
- `omit_sep_when_empty` — suppress separator when field is empty (default `True`)
- `enabled` — `False` excludes the component entirely (artwork defaults to `False`)
- `max_line_chars` — wrap long values onto continuation lines at this width (`null` = no wrap)
- `balance_lines` — distribute wrapped lines evenly when `max_line_chars` is set
- `next_component_position` — where the next component starts after a wrapped field:
  `'end_of_text'` (after all wrapped lines) or `'end_of_first_line'` (on the same first line)

### JSON Export

Structured JSON output with sections → works hierarchy, also available.

---

## 7. API

Routes are split across focused modules under `backend/app/api/`:

- `imports.py` — upload, list, sections, preview, warnings, delete
- `overrides.py` — per-work override CRUD and exclude toggle
- `exports.py` — Tagged Text, JSON, XML, CSV exports (full import and per-section)
- `templates.py` — export template CRUD and duplication
- `normalisation_config.py` — global normalisation config
- `schemas.py` — centralised Pydantic request/response models
- `deps.py` — shared dependencies (DB session)
- `import_routes.py` — thin aggregation hub that includes all sub-routers

All routes under `/`. Protected by API key if `API_KEY` env var is set.
CORS middleware is enabled when `CORS_ORIGINS` env var is set.

| Method | Path                                       | Description                               |
| ------ | ------------------------------------------ | ----------------------------------------- |
| POST   | `/import`                                  | Upload Excel file                         |
| GET    | `/imports`                                 | List all imports                          |
| DELETE | `/imports/{id}`                            | Delete import and all data                |
| GET    | `/imports/{id}/sections`                   | List sections with works                  |
| GET    | `/imports/{id}/warnings`                   | Validation warnings for the import        |
| GET    | `/imports/{id}/preview`                    | Lightweight preview of all works          |
| PUT    | `/imports/{id}/works/{wid}/override`       | Set/update work override                  |
| GET    | `/imports/{id}/works/{wid}/override`       | Get current override                      |
| DELETE | `/imports/{id}/works/{wid}/override`       | Remove override                           |
| PATCH  | `/imports/{id}/works/{wid}/exclude`        | Exclude or re-include a work              |
| GET    | `/imports/{id}/export-tags`                | Export full import as Tagged Text         |
| GET    | `/imports/{id}/export-json`                | Export full import as JSON                |
| GET    | `/imports/{id}/export-xml`                 | Export full import as XML                 |
| GET    | `/imports/{id}/export-csv`                 | Export full import as CSV                 |
| GET    | `/imports/{id}/sections/{sid}/export-tags` | Export single section as Tagged Text      |
| GET    | `/imports/{id}/sections/{sid}/export-json` | Export single section as JSON             |
| GET    | `/imports/{id}/sections/{sid}/export-xml`  | Export single section as XML              |
| GET    | `/imports/{id}/sections/{sid}/export-csv`  | Export single section as CSV              |
| GET    | `/config`                                  | Get global normalisation config           |
| PUT    | `/config`                                  | Save global normalisation config          |
| GET    | `/templates`                               | List non-archived export templates        |
| GET    | `/templates/{id}`                          | Get full config of a template             |
| POST   | `/templates`                               | Create a new export template              |
| PUT    | `/templates/{id}`                          | Update a template (non-builtin only)      |
| DELETE | `/templates/{id}`                          | Soft-delete a template (non-builtin only) |
| POST   | `/templates/{id}/duplicate`                | Clone a template                          |

---

## 8. Frontend

`frontend/` — vanilla JS SPA served at `/ui`.

- Import list with upload and delete
- Section browser with collapsible sections
- Works table (work number, artist, title, price, edition, artwork, medium, include flag)
- Inline override editor per work
- Validation warnings panel per import (with filterable badge summary)
- Export buttons (full import and per-section) with template selector
- Templates page: list, create, edit, duplicate, delete (built-in templates are read-only)
- Config page: manage normalisation honorific tokens and display preferences
- Toast notifications for all async operations (replaces browser alerts)
- Button loading states with spinners during API calls

---

## 9. Database Migrations

`backend/alembic/` — Alembic migration framework.

- On startup, `alembic upgrade head` runs automatically.
- Existing databases without an `alembic_version` table are auto-stamped at the
  baseline revision before upgrading.
- Schema changes should be added as new Alembic revisions.

---

## 10. Design Principles

- Raw data is sacred and never mutated
- Normalisation is deterministic and idempotent
- Export rules are separate from parsing logic
- Override values are explicit (`null` means "no override", not "empty value")
- Structure over presentation
