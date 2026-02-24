# Catalogue Tool – Requirements

## 1. System Overview

The Royal Academy's annual Summer Exhibition publishes a printed catalogue.
The editorial team prepares exhibition data in Excel spreadsheets; this tool
ingests those spreadsheets, lets editors review and correct the data, and
generates InDesign Tagged Text files ready for import into the catalogue layout.

The system supports two data products:

- **List of Works** — the main exhibition catalogue (Import → Section → Work)
- **Artists' Index** — alphabetical index of exhibiting artists with catalogue numbers

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

#### List of Works

1. The system must accept Excel file uploads via API and UI.
2. Each upload must create a new immutable Import record.
3. The original filename must be stored.
4. The upload timestamp must be recorded.
5. All raw column values must be preserved exactly as received.
6. Imports can be deleted, cascading to all sections, works, overrides, and warnings.
7. Uploaded files must be validated before import:
   - Required columns (`Cat No`, `Title`, `Artist`) must be present.
   - Missing required columns must produce a clear error with "did you mean?" suggestions.
   - Non-Excel, corrupt, or empty files must be rejected with a clear error.
   - Missing optional columns must produce validation warnings (not errors).
   - Header-only spreadsheets (no data rows) must produce a warning.
8. Re-import: a new Excel file can replace the data of an existing import while
   preserving editorial overrides matched by catalogue number.

#### Artists' Index

1. Excel files with a different column schema (`Last Name`, `Cat Nos` required;
   `Title`, `First Name`, `Quals`, `Company`, `Address 1` optional).
2. Multi-artist cells (e.g. `& Peter St John` in `Last Name`) must be parsed
   to extract primary and second artist names.
3. Company vs individual must be auto-detected (last name only, no first name or quals).
4. RA member status must be detected from qualification tokens.
5. Rows must be merged by identity key when they share the same name/quals
   and have no courtesy address (`Address 1`).
6. Known Artists lookup must be applied to correct names and set RA status.

---

### 2.2 Data Structure

The system must model two product types:

#### List of Works

Import → Section → Work

Each Import has many Sections; each Section has many Works.  
Sections are ordered by `(import_id, position)`.  
Works are ordered by `(section_id, position_in_section)`.

#### Artists' Index

Import → IndexArtist → IndexCatNumber

Each Index Import has many IndexArtists; each artist has many IndexCatNumbers.  
Artists are ordered by `sort_key`.  
Each artist may have an optional IndexArtistOverride.

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

The system must provide:

#### List of Works

| Method | Path                                       | Description                               |
| ------ | ------------------------------------------ | ----------------------------------------- |
| POST   | `/import`                                  | Upload Excel file                         |
| PUT    | `/imports/{id}/reimport`                   | Re-import with override preservation      |
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
| GET    | `/imports/{id}/export-diff`                | Diff against last export snapshot         |
| GET    | `/imports/{id}/sections/{sid}/export-tags` | Export single section as Tagged Text      |
| GET    | `/templates`                               | List non-archived LoW export templates    |
| GET    | `/templates/{id}`                          | Get full config of a template             |
| POST   | `/templates`                               | Create a new export template              |
| PUT    | `/templates/{id}`                          | Update a template (non-builtin only)      |
| DELETE | `/templates/{id}`                          | Soft-delete a template (non-builtin only) |
| POST   | `/templates/{id}/duplicate`                | Clone a template                          |
| GET    | `/config`                                  | Get global normalisation config           |
| PUT    | `/config`                                  | Save global normalisation config          |
| PATCH  | `/known-artists/{id}`                      | Update a known artist rule                |
| DELETE | `/known-artists/{id}`                      | Delete a known artist rule                |
| POST   | `/known-artists/seed`                      | Seed known artists from JSON              |
| GET    | `/imports/{id}/audit-log`                  | Audit log for an import                   |
| GET    | `/audit-log`                               | Global audit log                          |
| POST   | `/admin/cleanup-uploads`                   | Remove orphaned upload files              |

#### Artists' Index

| Method | Path                                         | Description                                               |
| ------ | -------------------------------------------- | --------------------------------------------------------- |
| POST   | `/index/import`                              | Upload Index Excel file                                   |
| GET    | `/index/imports`                             | List all index imports                                    |
| DELETE | `/index/imports/{id}`                        | Delete index import and all data                          |
| GET    | `/index/imports/{id}/artists`                | List all artists for an index import                      |
| GET    | `/index/imports/{id}/warnings`               | Validation warnings for the index import                  |
| GET    | `/index/imports/{id}/export-tags`            | Export index as Tagged Text (`?letter=`, `?template_id=`) |
| GET    | `/index/imports/{id}/artists/{aid}/override` | Get artist override                                       |
| PUT    | `/index/imports/{id}/artists/{aid}/override` | Set/update artist override                                |
| DELETE | `/index/imports/{id}/artists/{aid}/override` | Remove artist override                                    |
| PATCH  | `/index/imports/{id}/artists/{aid}/exclude`  | Exclude/re-include an artist                              |
| PATCH  | `/index/imports/{id}/artists/{aid}/company`  | Toggle company flag                                       |
| GET    | `/index/templates`                           | List index export templates                               |
| GET    | `/index/templates/{id}`                      | Get index template config                                 |
| POST   | `/index/templates`                           | Create index template                                     |
| PUT    | `/index/templates/{id}`                      | Update index template                                     |
| DELETE | `/index/templates/{id}`                      | Delete index template                                     |
| POST   | `/index/templates/{id}/duplicate`            | Clone index template                                      |

#### User Management (admin-only, Cognito mode)

| Method | Path                               | Description                          |
| ------ | ---------------------------------- | ------------------------------------ |
| GET    | `/users`                           | List all Cognito users with roles    |
| POST   | `/users`                           | Create user (email + role + temp pw) |
| PUT    | `/users/{username}`                | Change user role (re-assign group)   |
| POST   | `/users/{username}/disable`        | Disable user account                 |
| POST   | `/users/{username}/enable`         | Enable user account                  |
| POST   | `/users/{username}/reset-password` | Set temporary password               |

#### Authentication & Configuration

| Method | Path           | Description                                         |
| ------ | -------------- | --------------------------------------------------- |
| GET    | `/auth/config` | Returns Cognito pool/client IDs for frontend config |
| GET    | `/me`          | Returns current user email and role                 |
| GET    | `/health`      | Health check (used by ALB target group)             |

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

#### Artists' Index Export

- One paragraph per artist entry, styled with configurable paragraph style.
- Character styles for RA member surnames, RA qualifications, non-RA honorifics,
  catalogue numbers, and expert numbers.
- Configurable section separator between alphabetical letter groups.
- Per-letter export via `?letter=` query parameter.
- Template-controlled behaviour: quals lowercase, expert numbers, cat number separator.

---

### 2.8 Frontend UI

The system must provide a browser-based single-page application that allows:

- Uploading Excel files for both List of Works and Artists' Index.
- Browsing sections and works within a LoW import.
- Browsing artist entries grouped by letter within an Index import.
- Viewing normalisation warnings with filterable badge summaries.
- Applying and removing overrides per work (LoW) or per artist (Index).
- Configuring export settings (component order, styles, separators, toggles).
- Managing export templates for both LoW and Index on a combined Templates page.
- Exporting the full import, a single section (LoW), or a letter group (Index) as Tagged Text.
- Collapsible sections (LoW) and letter groups (Index) for focused editing.
- Login via Cognito (email + password) or legacy API key.
- Role badge in header showing current user role.
- Admin-only user management panel: create users, change roles, enable/disable, reset passwords.
- Staging environment banner.

---

## 3. Non-Functional Requirements

- Deterministic and idempotent parsing.
- No silent mutation of raw fields.
- PostgreSQL-backed with cascading deletes.
- REST API compliant.
- Versionable export specification.
- Stable ordering guarantees.
- Per-user authentication via AWS Cognito JWT (with API key fallback for legacy use).
- Three-tier role model: Viewer / Editor / Admin (mapped from Cognito groups).
- In-app user management for admins (create, role change, enable/disable, password reset).
- Audit log with user attribution (email recorded per action).
- Deployable via Docker / ECS Fargate with GitHub Actions CI/CD.
- Branch-based deployment: working branches → staging, main → production.
- HTTPS with ACM certificates and ALB termination.

---

## 4. Data Requirements

- UUID primary keys.
- Cascading deletes on Import (sections, works, overrides, warnings).
- Unique `(section_id, position_in_section)` per work.
- Import immutability after creation.

---

## 5. Constraints

- Excel structure must match the expected column schema
  (required: `Cat No`, `Title`, `Artist`; optional: `Gallery`, `Price`, `Edition`, `Artwork`, `Medium`).
- Uploads with missing required columns are rejected with a clear error message.
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

- Advanced title casing rules (LPG eccentricities).
- Undo / revision history for overrides.
- Bulk override import from Excel.
- Multi-user conflict resolution (optimistic locking).
- PDF preview generation.
- Webhook / notification on import completion.
