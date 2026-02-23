# Catalogue tool – architecture

## 1. System overview

The Catalogue Tool ingests Royal Academy exhibition catalogue data,
applies editorial overrides, and generates InDesign-ready Tagged Text exports.
It supports two products:

1. **List of Works (LoW)** — structured catalogue entries grouped by gallery section.
2. **Artists' Index** — alphabetical artist listing with catalogue number references.

### List of Works data flow

```
Excel Upload
  → Import Record (immutable)
  → Sections
  → Works (raw + normalised fields)
  → [Editorial Overrides]
  → Export Layer  →  InDesign Tagged Text / JSON / XML / CSV
```

### Artists Index data flow

```
Excel Upload
  → Import Record (immutable)
  → IndexArtists (parsed from multi-artist cells)
  → IndexCatNumbers (per artist)
  → [Editorial Overrides]
  → Export Layer  →  InDesign Tagged Text (letter-grouped)
```

---

## 2. Technology stack

| Layer      | Technology                        |
| ---------- | --------------------------------- |
| API        | Python 3.12, FastAPI, Uvicorn     |
| ORM        | SQLAlchemy 2.0                    |
| Migrations | Alembic                           |
| Validation | Pydantic v2                       |
| Database   | PostgreSQL 16                     |
| Frontend   | Vanilla JS SPA, served by FastAPI |
| Deployment | Docker / docker-compose           |
| Testing    | pytest (448 tests)                |

---

## 3. Data model

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

Stores export templates and global normalisation config in a single table,
distinguished by `config_type`:

- `'template'` — List of Works export template
- `'index_template'` — Artists' Index export template
- `'normalisation'` — global normalisation configuration

Columns:

- `id` (UUID), `name`, `config` (JSONB), `config_hash`, `config_type`
- `is_builtin` — `True` for seed templates shipped with the repository
- `slug` — short identifier used for seed deduplication (e.g. `ra-default`)
- `archived` — soft-delete flag
- `created_at`

Built-in templates are seeded from `backend/seed_templates/*.json` on startup
and upserted (name + config updated) whenever the file's hash has changed.
The JSON field `_config_type` in seed files determines the `config_type`.

### IndexArtist

One parsed artist entry within an Index import.

- `id`, `import_id`, `sort_key`, `display_name`, `raw_name`
- `qualifier` — RA/Hon RA/Hon RWS etc.
- `is_ra_member`, `is_company`, `is_linked`, `is_multi_name`
- `second_artist_name`, `second_artist_qualifier`, `second_artist_is_ra`
- `exclude` — omit from export (default `False`)
- `normalised_name`, `normalised_honorifics`

### IndexCatNumber

One catalogue number belonging to an `IndexArtist`.

- `id`, `artist_id`, `cat_no`, `expert_no`

### IndexArtistOverride

Optional editorial corrections for a single artist entry.

- `display_name_override`, `qualifier_override`, `is_ra_member_override`
- `sort_key_override`, `second_artist_name_override`
- `second_artist_qualifier_override`, `second_artist_is_ra_override`
- `cat_numbers_override` (JSON list)

### IndexArtistValidationWarning

Validation warnings recorded during Index import.

- `import_id`, `artist_id`, `warning_type`, `field`, `raw_value`, `message`

---

## 4. Normalisation layer

### List of Works normalisation

`backend/app/services/normalisation_service.py`

- **Price**: strips currency symbols, parses decimals; passes through `NFS`, `_`, blank
- **Edition**: parses `X` or `X at £Y` patterns; edition of 0 is suppressed in export
- **Artwork**: parses integer number of pieces from `raw_artwork`
- **Medium**: trimmed, passed through as-is
- **Honorifics**: split from artist name using known suffix list (RA, Hon RA, etc.)

Principles: deterministic, idempotent, raw data never mutated.

### Artists Index normalisation

`backend/app/services/index_importer.py`

The Index importer parses artist data from a different Excel schema and applies
multi-pass normalisation.

#### Index Excel schema

- **Required columns**: `Last Name`, `Cat Nos`
- **Optional columns**: `Title`, `First Name`, `Quals`, `Company`, `Address 1`

Header validation uses fuzzy matching (`difflib.get_close_matches`) to suggest
corrections for misspelled column names.

#### Multi-artist parsing

When `last_name` starts with `"and "` or `"& "`, the row is treated as a
multi-artist entry (e.g. "& Peter St John"):

1. `first_name` is assumed to contain the primary artist's full name
2. Known qualification tokens (RA, OBE, CBE, etc.) are stripped from
   the end of `first_name` and merged into `quals`
3. The remaining `first_name` is split — the last word becomes `last_name`,
   everything before becomes `first_name`
4. The original `last_name` value is stored as `second_artist`

#### Multi-name detection

Names containing `"and"`, `"with"`, or `&` (regex `\band\b|\bwith\b|\s&\s`)
generate a `multi_artist_name` validation warning. Unlike multi-artist parsing,
this only warns — it does not restructure the row.

#### Company detection

Heuristic: has `last_name` AND no `first_name` AND no `quals`.
If detected and no `Company` column value exists, `last_name` is copied into
`company`. Generates a `possible_company` validation warning.

#### RA member detection

The `quals` string is checked (whole-word, case-insensitive) for tokens:
`RA`, `PRA`, `PPRA`, `HON RA`, `HONRA`, `RA ELECT`, `EX OFFICIO`.

#### Sort key generation

`build_sort_key(last_name, first_name)` → `"{last_name} {first_name}"`,
lowercased, accent-stripped (NFKD + remove combining marks).
Companies (no `last_name`) sort by `first_name`.

#### Display Name (Index Name)

`build_index_name()` composes the final display string:

| Type         | Pattern                                      | Example                              |
| ------------ | -------------------------------------------- | ------------------------------------ |
| Standard     | `Surname, [Title] FirstName quals`           | `Adams, Roger`                       |
| RA member    | `Surname, FirstName quals`                   | `Parker, Cornelia cbe ra`            |
| Company      | `CompanyName`                                | `Assemble`                           |
| Multi-artist | `Surname, FirstName quals, and SecondArtist` | `Caruso, Adam ra, and Peter St John` |

#### Cat Number parsing

Split on `;` or `,`; each token is stripped. Only digit-only tokens are
stored as integers.

#### Artist merging (Pass 2)

Rows are grouped by identity key: `title|first_name|last_name|quals`
(all lowered and stripped). Rows **without** an `Address 1` (courtesy) value
are merged into a single artist entry (cat numbers combined). Rows **with**
an `Address 1` value each become separate entries (one per courtesy address).

---

## 4.1 Spreadsheet validation

### List of Works

`backend/app/services/excel_importer.py`

Before importing, the header row is validated:

- **Required columns** (`Cat No`, `Title`, `Artist`) — missing any → 400 error
  with a "did you mean?" suggestion when a close match exists.
- **Optional columns** (`Gallery`, `Price`, `Edition`, `Artwork`, `Medium`) —
  missing → import proceeds but a `missing_column` validation warning is stored.
- **Non-Excel files** and corrupt/empty spreadsheets → 400 with a clear message.
- **Header-only spreadsheets** → import succeeds with an `empty_spreadsheet` warning.

### Artists Index

`backend/app/services/index_importer.py`

- **Required columns** (`Last Name`, `Cat Nos`) — missing any → 400 error.
- **Optional columns** (`Title`, `First Name`, `Quals`, `Company`, `Address 1`) —
  missing → import proceeds normally.
- Fuzzy-match "did you mean?" suggestions for misspelled columns.

---

## 4.2 Known artists

`backend/app/models/known_artist_model.py`  
`backend/app/api/known_artists.py`

A lookup table of known artists with pre-defined attributes. Used during
Index import to correct names and set RA status without manual overrides.

### KnownArtist model

| Column                   | Type    | Purpose                                  |
| ------------------------ | ------- | ---------------------------------------- |
| `id`                     | UUID PK |                                          |
| `match_first_name`       | Text    | Match criterion (spreadsheet first name) |
| `match_last_name`        | Text    | Match criterion (spreadsheet last name)  |
| `resolved_first_name`    | Text    | Output first name                        |
| `resolved_last_name`     | Text    | Output last name                         |
| `resolved_quals`         | Text    | Output qualifications                    |
| `resolved_second_artist` | Text    | Output second artist suffix              |
| `resolved_is_company`    | Boolean | Override company flag                    |
| `notes`                  | Text    | Human-readable explanation               |

Unique constraint on `(match_first_name, match_last_name)`.

### Matching logic

All `KnownArtist` rows are loaded into an in-memory dict keyed by
`(match_first_name.strip().lower(), match_last_name.strip().lower())`.
NULL fields normalise to empty string. Matching is **exact** (no fuzzy matching).

### Seed data

Stored at `backend/seed_templates/known-artists.json` — a JSON array of objects.
Seeded via `POST /known-artists/seed`; existing matches are skipped.
`""` means "clear this field to None"; `null` or absent means "don't override".

### Resolution priority

Known Artist values sit between normalised values and user overrides in the
resolution chain:

1. **User override** (highest priority)
2. **Known Artist lookup**
3. **Normalised values** (lowest priority)

---

## 5. Override services

### List of Works

`backend/app/services/override_service.py`

`resolve_effective_work(work, override) → EffectiveWork`

Merges a Work ORM object with an optional WorkOverride. Each field prefers the
override value if set, otherwise falls back to the normalised Work value.
Returns an `EffectiveWork` dataclass used by the export renderer.

### Artists Index

`backend/app/services/index_override_service.py`

`resolve_index_artist(artist, override, known_artist=None) → EffectiveIndexArtist`

Merges three layers for each IndexArtist:

1. **User override** (`IndexArtistOverride.*_override` fields)
2. **Known Artist lookup** (`KnownArtist.resolved_*` fields)
3. **Normalised values** (from importer heuristics)

Convention: `""` (empty string) means "clear this field to None";
`None` means "don't override" (fall through to next layer).

`EffectiveIndexArtist` contains: `index_name`, `title`, `first_name`,
`last_name`, `quals`, `company`, `second_artist`, `is_ra_member`, `is_company`,
`is_company_auto`, `sort_key`, `include_in_export`.

Company handling: company flag follows override > known_artist > auto-detected.
Companies never have a `second_artist` (cleared automatically).
Sort key is recomputed from resolved values.

---

## 5.1 Re-import with override preservation

`backend/app/services/excel_importer.py` → `reimport_excel()`

Route: `PUT /imports/{id}/reimport` (LoW only; Index does not yet have re-import).

1. Parse and validate the new Excel file (fail fast before touching data)
2. Snapshot all existing overrides + `include_in_export` flags, keyed by `raw_cat_no`
3. Delete all old data (work overrides → warnings → works → sections)
4. Re-create sections and works from the new spreadsheet
5. For each new work, if its `raw_cat_no` matches a preserved key, restore the
   override and exclude flag (one-to-one, first match wins)
6. Count matched / added / removed works
7. Audit log entry with action `"reimport"` and counts

Return: `{import_id, matched, added, removed, overrides_preserved}`

---

## 5.2 Export diff

`backend/app/services/export_diff_service.py`

Compares resolved export data against a previously saved snapshot.

- `save_export_snapshot(import_id, template_id, db)` — saves current resolved
  data as an `ExportSnapshot` row
- `compute_diff(import_id, template_id, db)` — computes a field-level diff
  between the current data and the most recent snapshot

Diff algorithm:

1. Flatten section-grouped data into a dict keyed by catalogue number
   (unnamed works get synthetic keys `__unnamed_N`; duplicates disambiguated
   with `__posX_Y`)
2. Compute added / removed / common key sets
3. For common keys, compare each field: `number`, `artist`, `honorifics`,
   `title`, `price_numeric`, `price_text`, `edition_total`,
   `edition_price_numeric`, `artwork`, `medium`, plus section membership
4. Return `{has_changes, previous_exported_at, added[], removed[], changed[], unchanged_count}`

If no previous snapshot exists: `{has_changes: false, no_previous_export: true}`.

---

## 6. Export layer

### List of Works export

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

### JSON export

Structured JSON output with sections → works hierarchy, also available.

### Artists Index export

`backend/app/services/index_renderer.py`

Renders the Artists' Index as InDesign Tagged Text.

#### IndexExportConfig

Controls all index export behaviour:

- `entry_style` — paragraph style for each artist entry
- `ra_surname_style` — character style for RA member surnames
- `ra_caps_style` — character style for RA qualifications
- `cat_no_style` — character style for catalogue numbers
- `honorifics_style` — character style for non-RA honorifics
- `expert_numbers_style` — character style for expert numbers
- `quals_lowercase` — render qualifications in lowercase
- `expert_numbers_enabled` — include expert numbers in export
- `cat_no_separator` — separator between catalogue numbers (default `,`)
- `cat_no_separator_style` — character style for the separator
- `section_separator` — separator between letter groups (`paragraph`, `column_break`, `frame_break`, `page_break`, `none`)
- `section_separator_style` — paragraph style for the separator

#### Letter group logic

- `_letter_key(entry)` — returns uppercase first letter of `sort_key`, or `#` for digits
- Entries are grouped by letter key and sorted within each group
- `_section_sep()` inserts the configured separator between groups

#### Second artist handling

- Linked entries (`&`) and multi-name entries render `second_artist_name`
  with independent RA styling when `second_artist_is_ra` is set

---

## 7. API

Routes are split across focused modules under `backend/app/api/`:

- `imports.py` — upload, re-import, list, sections, preview, warnings, delete
- `overrides.py` — per-work override CRUD and exclude toggle
- `exports.py` — Tagged Text, JSON, XML, CSV exports (full import and per-section)
- `templates.py` — LoW export template CRUD and duplication
- `normalisation_config.py` — global normalisation config
- `known_artists.py` — Known Artists CRUD and seed
- `index.py` — Index import, artists, overrides, warnings, export
- `index_templates.py` — Index export template CRUD and duplication
- `schemas.py` — centralised Pydantic request/response models
- `deps.py` — shared dependencies (DB session)
- `import_routes.py` — thin aggregation hub that includes all sub-routers
- `auth.py` — API key middleware

All routes under `/`. Protected by API key if `API_KEY` env var is set.
CORS middleware is enabled when `CORS_ORIGINS` env var is set.

### List of Works routes

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
| GET    | `/templates`                               | List non-archived LoW export templates    |
| GET    | `/templates/{id}`                          | Get full config of a template             |
| POST   | `/templates`                               | Create a new export template              |
| PUT    | `/templates/{id}`                          | Update a template (non-builtin only)      |
| DELETE | `/templates/{id}`                          | Soft-delete a template (non-builtin only) |
| POST   | `/templates/{id}/duplicate`                | Clone a template                          |
| PUT    | `/imports/{id}/reimport`                   | Re-import with override preservation      |
| GET    | `/imports/{id}/export-diff`                | Diff against last export snapshot         |
| GET    | `/imports/{id}/audit-log`                  | Audit log for an import                   |
| GET    | `/audit-log`                               | Global audit log                          |
| POST   | `/admin/cleanup-uploads`                   | Remove orphaned upload files              |
| GET    | `/known-artists`                           | List all known artist rules               |
| POST   | `/known-artists`                           | Create a known artist rule                |
| PATCH  | `/known-artists/{id}`                      | Update a known artist rule                |
| DELETE | `/known-artists/{id}`                      | Delete a known artist rule                |
| POST   | `/known-artists/seed`                      | Seed known artists from JSON              |

### Artists Index routes

| Method | Path                                         | Description                          |
| ------ | -------------------------------------------- | ------------------------------------ |
| POST   | `/index/import`                              | Upload Index Excel file              |
| GET    | `/index/imports`                             | List all Index imports               |
| DELETE | `/index/imports/{id}`                        | Delete Index import and all data     |
| GET    | `/index/imports/{id}/artists`                | List artists for an Index import     |
| GET    | `/index/imports/{id}/artists/{aid}/warnings` | Warnings for a specific artist       |
| GET    | `/index/imports/{id}/export-tags`            | Export full Index as Tagged Text     |
| GET    | `/index/imports/{id}/export-tags?letter=A`   | Export single letter group           |
| PUT    | `/index/imports/{id}/artists/{aid}/override` | Set/update artist override           |
| GET    | `/index/imports/{id}/artists/{aid}/override` | Get current artist override          |
| DELETE | `/index/imports/{id}/artists/{aid}/override` | Remove artist override               |
| PATCH  | `/index/imports/{id}/artists/{aid}/exclude`  | Exclude or re-include an artist      |
| PATCH  | `/index/imports/{id}/artists/{aid}/company`  | Toggle company flag                  |
| GET    | `/index/templates`                           | List non-archived Index templates    |
| GET    | `/index/templates/{id}`                      | Get full config of an Index template |
| POST   | `/index/templates`                           | Create a new Index template          |
| PUT    | `/index/templates/{id}`                      | Update an Index template             |
| DELETE | `/index/templates/{id}`                      | Soft-delete an Index template        |
| POST   | `/index/templates/{id}/duplicate`            | Clone an Index template              |

---

## 8. Frontend

`frontend/` — vanilla JS SPA served at `/ui`.

### Navigation

Hash-based routing (`window.addEventListener('hashchange', router)`).
Main navigation bar:

| Nav item      | Hash          | View                    |
| ------------- | ------------- | ----------------------- |
| List of Works | `#/`          | LoW import list         |
| Artists Index | `#/index`     | Index import list       |
| Templates     | `#/templates` | Combined templates page |
| Audit Log     | `#/audit`     | Audit log viewer        |
| Settings      | `#/settings`  | Normalisation config    |

Deep links: `#/import/{id}` (LoW detail), `#/index/{id}` (Index detail),
`#/templates/{id}/edit`, `#/index-templates/{id}/edit`.

### List of Works

- Import list with upload and delete
- Section browser with collapsible sections and per-section export
- Works table (work number, artist, title, price, edition, artwork, medium, include flag)
- Inline override editor per work with three-state resolved fields
- Validation warnings panel per import (filterable badge summary by warning type)
- Export buttons (full import and per-section) with template selector

### Artists Index

- Index import list with upload and delete
- Artist entries grouped by letter in collapsible `<details>` blocks
- Artist detail expansion with override editing and warning display
- RA member and company indicators (styled badges)
- Linked / multi-name entry indicators with enriched flag styling
- Per-letter export buttons on each letter group heading
- Warning type filter for targeted review

### Shared

- Combined Templates page for both LoW and Index templates (separate tabs)
- Full template CRUD: list, create, edit, duplicate, delete (built-in templates read-only)
- Config page: manage normalisation honorific tokens and display preferences
- Toast notifications for all async operations
- Button loading states with spinners during API calls

---

## 9. Database migrations

`backend/alembic/` — Alembic migration framework.

- On startup, `alembic upgrade head` runs automatically.
- Existing databases without an `alembic_version` table are auto-stamped at the
  baseline revision before upgrading.
- Schema changes should be added as new Alembic revisions.

---

## 10. Design principles

- Raw data is sacred and never mutated
- Normalisation is deterministic and idempotent
- Export rules are separate from parsing logic
- Override values are explicit (`null` means "no override", not "empty value")
- Structure over presentation
