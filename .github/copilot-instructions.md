# Copilot workspace instructions

## Project overview

The **RA Summer Exhibition Catalogue Tool** ingests exhibition data from Excel
spreadsheets, applies editorial overrides, and exports InDesign-ready Tagged
Text for the Royal Academy Summer Exhibition catalogue. It produces two
products:

1. **List of Works (LoW)** — structured catalogue entries grouped by gallery
   section, exported as Tagged Text / JSON / XML / CSV.
2. **Artists' Index** — alphabetical artist listing with catalogue number
   references, exported as InDesign Tagged Text.

## Tech stack

| Layer      | Technology                                          |
| ---------- | --------------------------------------------------- |
| Backend    | Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic       |
| Database   | PostgreSQL 16 (Docker local, RDS in staging/prod)   |
| Frontend   | Vanilla JS SPA (`frontend/app.js` ~5 500 lines)     |
| Testing    | pytest (~769 tests), SQLite in-memory                |
| Deployment | Docker Compose (local), ECS Fargate (staging/prod)  |
| Auth       | AWS Cognito (JWT) / API key; disabled locally        |

## Key directories

| Path                        | Purpose                                           |
| --------------------------- | ------------------------------------------------- |
| `backend/app/api/`          | FastAPI route modules and Pydantic schemas         |
| `backend/app/models/`       | SQLAlchemy ORM models                              |
| `backend/app/services/`     | Business logic (import, normalise, resolve, export)|
| `backend/alembic/versions/` | Database migrations (auto-run on container startup)|
| `backend/seed_templates/`   | Default templates and known-artist seed data       |
| `frontend/`                 | SPA: `app.js`, `style.css`, `index.html`           |
| `tests/`                    | Pytest suite (SQLite in-memory, no Docker needed)  |
| `docs/`                     | Architecture, dev guide, export spec, roadmap      |

## Data flow

```
Spreadsheet upload → Parse & normalise → Store raw + normalised
  → Known Artist lookup → User overrides → Resolved output → Export
```

## Critical conventions

### Three-layer override resolution (Artists' Index)

Values resolve left-to-right — first non-null wins:

1. **User override** (`IndexArtistOverride`) — highest priority
2. **Known Artist** (`KnownArtist`) — pre-configured corrections
3. **Normalised** (from importer heuristics) — lowest priority

**Null vs empty string semantics:**

- `None` / `null` = "no override — fall through to next layer"
- `""` (empty string) = "clear this field to blank"
- `"value"` = "use this explicit override"

This convention applies everywhere overrides exist (LoW `WorkOverride`,
Index `IndexArtistOverride`, `KnownArtist`).

### Raw data is immutable

Raw columns on Import / Work / IndexArtist are never modified after import.
Normalised fields are derived deterministically from the raw data.

### InDesign Tagged Text format

- Header: `<ASCII-MAC>` with Mac Roman byte encoding
- Line endings: CR (`\r`) — one per paragraph
- Characters outside Mac Roman: `<0x####>` numeric escapes
- Character styles: `<cstyle:StyleName>value<cstyle:>` or
  `<CharStyle:StyleName>value<CharStyle:>`
- Paragraph styles: `<pstyle:StyleName>` or `<ParaStyle:StyleName>`
- Character styles wrap **only** the value, never surrounding separators
  (commas, spaces, tabs)

### Multi-artist entries (Index)

An entry can have up to three artists. Additional artists are styled
independently based on their `artistN_ra_styled` flag. With two artists,
artist 2 gets an "and" prefix. With three, only the last gets "and"
(Oxford-comma style).

### Boolean override fields

Boolean overrides (e.g. `is_company_override`, `artist1_ra_styled_override`)
are tri-state: `None` = no override, `True` = force on, `False` = force off.

## Development workflow

### Running locally

```bash
docker compose up -d           # starts app + PostgreSQL
open http://localhost:8000/ui
docker compose up -d --build app  # rebuild after changes
```

Never run `python backend/app/main.py` directly — the app needs Docker
PostgreSQL and the container's upload volume.

### Running tests

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest tests/ -q       # full suite (~769 tests)
python -m pytest tests/ -x -q    # stop on first failure
```

Tests use SQLite in-memory — no Docker required.

### Database migrations (Alembic)

**Every** column change in a SQLAlchemy model requires a corresponding Alembic
migration. Tests won't catch a missing migration — they use `create_all()`,
not Alembic. Always verify against Docker after creating a migration:

```bash
docker compose up -d --build app
docker compose logs app --tail=20   # look for "Running upgrade"
```

If you add columns to `index_artists`, check whether `index_artist_overrides`
also needs updating (and vice versa).

## Common pitfalls

| Mistake                                          | Prevention                                                                                                                |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------- |
| Changed model but forgot Alembic migration       | Tests won't catch this — always create a migration                                                                        |
| Tests pass but Docker 500s                       | DB schema out of sync — migration is missing                                                                              |
| Index warning type not showing in UI             | Update `_IDX_WARNING_LABELS` map and `_IDX_CHANGED_TYPES` set in `app.js`                                                 |
| LoW warning type not showing in UI               | Update `_LOW_WARNING_LABELS` map and `_LOW_CHANGED_TYPES` set in `app.js`                                                 |
| LoW detail panel shows stale data                | `_workCache` is populated in `renderSections` — always refresh via `_showWorkDetailPanel` after override save/delete       |
| LoW warning badges missing from detail panel     | `_warningsByWorkId` is populated in `renderWarningsPanel` — must be called before sections render                         |
| `.env` has `API_KEY=value`                       | Clear to `API_KEY=` for no-auth mode locally                                                                              |

## Validation warnings

Two categories displayed with distinct badge colours:

- **Changed (blue)** — normalisation engine modified data (e.g.
  `whitespace_trimmed`, `multi_artist_name_changed`, `ra_member_detected`)
- **Suspected (amber)** — may need human review (e.g.
  `multi_artist_name_suspected`, `ra_styling_ambiguous`, `non_ascii_characters`)

Warning types are free-text strings in the `ValidationWarning` table — no
enum or migration needed to add new types.

## Seed templates

JSON files in `backend/seed_templates/` are upserted on startup. The app
compares config hashes and only writes when content changes. The `_config_type`
field in the JSON determines whether it's a `template`, `index_template`, or
`normalisation` config.

## Further docs

- [docs/architecture_v1.md](docs/architecture_v1.md) — full data model and system architecture
- [docs/dev-guide.md](docs/dev-guide.md) — developer operations guide
- [docs/export_spec_v1.md](docs/export_spec_v1.md) — InDesign Tagged Text format specification
- [docs/roadmap.md](docs/roadmap.md) — feature roadmap and maintenance backlog
