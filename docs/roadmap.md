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
- Route integration tests using SQLite in-memory + StaticPool (114 tests total)

---

## Future Considerations

- Role-based access (read-only vs editorial vs admin)
- Cloud storage for uploaded Excel files
- Structured audit log viewer in UI
- Duplicate import detection
- CSV export format
- Print-preview rendering
