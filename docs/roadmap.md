# Catalogue Tool – Roadmap

## Phase 1 – Core Infrastructure ✅

- Excel upload and import model
- Sections + Works (raw and normalised fields)
- Deterministic normalisation (price, edition, medium, honorifics)
- InDesign Tagged Text export
- Import deletion and listing

---

## Phase 2 – Data Integrity ✅

- 63-test pytest suite
- Validation warnings for unparseable fields
- Edition anomaly detection
- Edge-case price parsing (NFS, \_, blanks, decimals)

---

## Phase 3 – Editorial Controls ✅

- Work overrides (title, artist, honorifics, price, edition, medium)
- Exclude individual works from export
- Audit log model
- Override removal

---

## Phase 4 – Export Expansion ✅

- JSON export
- Configurable component order, separators, and character styles
- Per-component enabled/disabled toggle
- Per-component omit-separator-when-empty option
- Section-level Tagged Text export
- Artwork field support
- ASCII-MAC encoding with Mac Roman escape fallback
- Line wrapping with `max_line_chars` and `balance_lines`
- `next_component_position` for layout after wrapped fields
- Extended separator types (`soft_return`, `hard_return`, `right_tab`)

---

## Phase 5 – UI Layer ✅

- Vanilla JS SPA at `/ui`
- Import upload
- Section browser with collapsible sections
- Works table with artwork column
- Inline override editor
- Settings panel (component order, styles, number formatting)
- Export buttons (full import and per section)

---

## Phase 6 – Production Hardening ✅

- API key authentication
- Docker + docker-compose deployment
- PostgreSQL 16
- `.env.example` for configuration

---

## Phase 7 – Export Templates ✅

- Named export templates stored in the database (`Ruleset` model)
- Template CRUD API (`GET/POST/PUT/DELETE /api/templates`)
- Duplicate endpoint (clone any template, including built-ins)
- Built-in seed templates shipped as JSON files in `backend/seed_templates/`
- Seed upsert on startup: name and config updated when JSON file hash changes
- Built-in templates are read-only (403 on edit/delete); duplicate to customise
- Templates UI: list, create, edit, view (built-ins), duplicate, delete

---

## Phase 8 – Normalisation Config & Test Expansion ✅

- Global normalisation config endpoint (`GET/PUT /api/config`)
- Configurable honorific token list persisted to the database
- Config UI page
- Route integration tests using SQLite in-memory + StaticPool

---

## Phase 9 – Production Hardening & Code Quality ✅

- Split monolithic `import_routes.py` (1015 lines) into 7 focused modules
- Fixed N+1 override queries in export renderer with batch loading
- Secured upload path (filename sanitisation + UUID prefix)
- Pinned all dependency versions in `requirements.txt`
- Consolidated Pydantic schemas into `schemas.py`
- Removed unused `Export` model and database table
- Added CORS middleware (configurable via `CORS_ORIGINS`)
- Centralised upload path via `UPLOAD_DIR` config
- Alembic database migrations (auto-upgrade on startup, auto-stamp for existing DBs)
- 39 new route-level integration tests (172 tests total)

---

## Phase 10 – Frontend Polish ✅

- Toast notification system (slide-in/out, auto-dismiss, error/success/info)
- Replaced all `alert()` calls with non-blocking toast notifications
- Button loading states with spinners during async operations
- Prevent double-clicks with disabled state during API calls
- Success feedback toasts for delete and export operations

---

## Phase 11 – Spreadsheet Validation ✅

- Validate required columns on upload (`Cat No`, `Title`, `Artist`)
- Clear 400 error with "did you mean?" fuzzy-match suggestions for misspelled columns
- Reject non-Excel, corrupt, and empty files with clear error messages
- Validation warnings for missing optional columns
- Warning for header-only spreadsheets (no data rows)
- 19 new tests for validation logic (172 tests total)

---

## Phase 12 – Artists' Index: Core Pipeline ✅

- Index data model: `IndexArtist`, `IndexCatNumber`, `IndexArtistOverride`, `IndexArtistValidationWarning`
- Excel import with multi-artist cell parsing (semicolons, commas, "and"/"&" separators)
- Linked entry detection (e.g. "Boyd & Evans")
- Multi-name detection (e.g. "Gilbert and George")
- Company / collective detection (e.g. "Assemble")
- RA member identification via known-artists lookup
- Sort key generation (surname-first normalisation)
- Normalisation warnings per artist entry
- Index import API: upload, list, delete, artists listing
- InDesign Tagged Text export with RA member styling
  (surname style, qualifications style, dual character styles)
- 100+ new tests

---

## Phase 13 – Artists' Index: Overrides & Warnings ✅

- Per-artist override CRUD (display name, qualifier, RA status, sort key,
  second artist fields, catalogue number list)
- Exclude / re-include individual artists from export
- Company flag toggle
- Three-state resolved fields in the frontend (original → override → resolved)
- Warning type filter for targeted review
- Enriched flag styling (RA badge, company badge, linked/multi-name indicators)

---

## Phase 14 – Artists' Index: Export Templates ✅

- `IndexExportConfig` with 12 configurable fields
- Separate `index_template` config_type in the Ruleset model
- Index template CRUD API (`/index/templates`)
- Seed template: `index-default.json`
- Combined Templates page in UI (LoW + Index tabs)
- Template editor: paragraph/character styles, toggles, separators

---

## Phase 15 – Artists' Index: Letter Groups & Export ✅

- Letter-group rendering: entries grouped by first letter of sort key
- Configurable section separator between letter groups
  (paragraph, column_break, frame_break, page_break, none)
- Section separator paragraph style
- Cat number separator and separator style
- Collapsible letter sections in frontend (`<details>` blocks)
- Per-letter export via `?letter=` query parameter
- Filter hides empty letter groups
- 448 tests total

---

## Future Considerations

- Role-based access (read-only vs editorial vs admin)
- Cloud storage for uploaded Excel files
- Structured audit log viewer in UI
- Print-preview rendering
