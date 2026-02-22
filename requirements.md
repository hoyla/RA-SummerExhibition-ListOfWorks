# Catalogue Tool – Requirements

## 1. System Overview

The Catalogue Tool ingests Royal Academy exhibition catalogue Excel files,
applies editorial overrides, and generates InDesign-ready Tagged Text exports.

The system must:

- Preserve raw source data exactly as received.
- Apply deterministic, idempotent normalisation rules.
- Maintain structural integrity of sections and works.
- Allow editorial overrides without mutating the original import.
- Generate clean, import-ready InDesign Tagged Text exports.
- Provide a browser-based UI for editorial workflows.

---

## 2. Functional Requirements

### 2.1 Importing

1. The system must accept Excel file uploads via API and UI.
2. Each upload must create a new immutable Import record.
3. The original filename must be stored.
4. The upload timestamp must be recorded.
5. All raw column values must be preserved exactly as received.
6. Imports can be deleted, cascading to all sections, works, overrides, and warnings.

---

### 2.2 Data Structure

The system must model:

Import → Section → Work

Each Import has many Sections; each Section has many Works.  
Sections are ordered by `(import_id, position)`.  
Works are ordered by `(section_id, position_in_section)`.

---

### 2.3 Normalisation

The system must normalise the following fields deterministically:

#### Artist

- Trim leading/trailing whitespace.
- Separate name and honorifics using a known suffix list (RA, Hon RA, etc.).
- Preserve diacritics and punctuation.

#### Price

- Parse numeric prices into decimal values.
- Preserve text values: `NFS`, `_`.
- Treat blank price fields as `_`.
- Store both numeric and text representations.

#### Edition

- Parse patterns such as `Edition of 6 at £3,900.00` or `Edition of 27`.
- Extract `edition_total` and `edition_price_numeric` (if present).
- Suppress meaningless entries (`Edition of 0`, `Edition of 0 at £0.00`).
- Treat incomplete price values as unpriced editions.

#### Artwork

- Parse the artwork column as an integer (number of pieces).
- Store as `artwork` (nullable integer).

#### Medium

- Trim whitespace and trailing line breaks.
- Preserve descriptive content.

#### Validation Warnings

- When a raw field cannot be parsed to its expected type, a `ValidationWarning` must be recorded.
- Warnings must reference the import, work, field name, raw value, and a message.

---

### 2.4 Editorial Overrides

1. Any work may have an optional `WorkOverride` record.
2. Overrides may replace: title, artist name, artist honorifics, price (numeric or text), edition total, edition price, medium.
3. A `null` override field means "use the normalised Work value" — it is not the same as an empty string.
4. Overrides are resolved at export time, not stored as mutations.
5. Overrides can be set, updated, and removed via API and UI.

---

### 2.5 Export Configuration

1. Export behaviour must be controlled by a persistent `ExportConfig`.
2. Config must specify: currency symbol, number formatting, paragraph and character style names.
3. Config must specify an ordered list of components (fields) for each catalogue entry.
4. Each component must have: a separator after it, an option to omit the separator when the value is empty, and an enabled/disabled toggle.
5. Config must be retrievable and saveable via API.

---

### 2.6 API Endpoints

The system must provide (all under `/api/`):

| Method | Path                            | Description                          |
| ------ | ------------------------------- | ------------------------------------ |
| POST   | `/api/imports`                  | Upload Excel file                    |
| GET    | `/api/imports`                  | List all imports                     |
| DELETE | `/api/imports/{id}`             | Delete import and all data           |
| GET    | `/api/imports/{id}/sections`    | List sections with works             |
| PUT    | `/api/works/{id}/override`      | Set/update work override             |
| DELETE | `/api/works/{id}/override`      | Remove override                      |
| GET    | `/api/imports/{id}/export`      | Export full import as Tagged Text    |
| GET    | `/api/imports/{id}/export-json` | Export full import as JSON           |
| GET    | `/api/sections/{id}/export`     | Export single section as Tagged Text |
| GET    | `/api/config`                   | Get current export config            |
| POST   | `/api/config`                   | Save export config                   |

---

### 2.7 Export

The system must generate InDesign Tagged Text with:

- File header: `<ASCII-MAC>`.
- Byte encoding: Mac Roman; characters outside Mac Roman encoded as `<0x####>`.
- CR (`\r`) line endings, one per paragraph.
- Configured paragraph styles per section header and catalogue entry.
- Configured character styles per field.
- Components ordered and separated as specified in `ExportConfig`.
- Clean blank-line separation between sections.

Export rules must follow the documented export specification (`export_spec_v1.md`).  
Export logic must not contain parsing logic.

---

### 2.8 Frontend UI

The system must provide a browser-based single-page application that allows:

- Uploading Excel files.
- Browsing sections and works within an import.
- Viewing normalisation warnings.
- Applying and removing overrides per work.
- Configuring export settings (component order, styles, separators, toggles).
- Exporting the full import or a single section as Tagged Text.

---

## 3. Non-Functional Requirements

- Deterministic and idempotent parsing.
- No silent mutation of raw fields.
- PostgreSQL-backed with cascading deletes.
- REST API compliant.
- Versionable export specification.
- Stable ordering guarantees.
- API key authentication (optional; disabled when `API_KEY` env var is unset).
- Deployable via Docker / docker-compose.

---

## 4. Data Requirements

- UUID primary keys.
- Cascading deletes on Import (sections, works, overrides, warnings).
- Unique `(section_id, position_in_section)` per work.
- Import immutability after creation.

---

## 5. Constraints

- Excel structure must match the expected column schema.
- No inline formatting logic inside the export layer.
- Override values must be explicit nulls, not inferred from empty strings.

---

## 6. Assumptions

- Editorial team controls the Excel structure.
- InDesign uses the Tagged Text import workflow.
- Exhibition structure is strictly hierarchical (Import → Section → Work).
- Export formatting rules may evolve per exhibition but must remain versioned.

---

## 7. Future Considerations

- Role-based access (read-only vs editorial vs admin).
- Cloud storage for uploaded Excel files.
- Structured audit log viewer in UI.
- Duplicate import detection.
- CSV export format.
- Print-preview rendering.
