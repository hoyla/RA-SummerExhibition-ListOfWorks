# Catalogue Tool – roadmap

## Phase 1 – Core infrastructure ✅

- Excel upload and import model
- Sections + Works (raw and normalised fields)
- Deterministic normalisation (price, edition, medium, honorifics)
- InDesign Tagged Text export
- Import deletion and listing

---

## Phase 2 – Data integrity ✅

- 63-test pytest suite
- Validation warnings for unparseable fields
- Edition anomaly detection
- Edge-case price parsing (NFS, \_, blanks, decimals)

---

## Phase 3 – Editorial controls ✅

- Work overrides (title, artist, honorifics, price, edition, medium)
- Exclude individual works from export
- Audit log model
- Override removal

---

## Phase 4 – Export expansion ✅

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

## Phase 5 – UI layer ✅

- Vanilla JS SPA at `/ui`
- Import upload
- Section browser with collapsible sections
- Works table with artwork column
- Inline override editor
- Settings panel (component order, styles, number formatting)
- Export buttons (full import and per section)

---

## Phase 6 – Production hardening ✅

- API key authentication
- Docker + docker-compose deployment
- PostgreSQL 16
- `.env.example` for configuration

---

## Phase 7 – Export templates ✅

- Named export templates stored in the database (`Ruleset` model)
- Template CRUD API (`GET/POST/PUT/DELETE /api/templates`)
- Duplicate endpoint (clone any template, including built-ins)
- Built-in seed templates shipped as JSON files in `backend/seed_templates/`
- Seed upsert on startup: name and config updated when JSON file hash changes
- Built-in templates are read-only (403 on edit/delete); duplicate to customise
- Templates UI: list, create, edit, view (built-ins), duplicate, delete

---

## Phase 8 – Normalisation config & test expansion ✅

- Global normalisation config endpoint (`GET/PUT /api/config`)
- Configurable honorific token list persisted to the database
- Config UI page
- Route integration tests using SQLite in-memory + StaticPool

---

## Phase 9 – Production hardening & code quality ✅

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

## Phase 10 – Frontend polish ✅

- Toast notification system (slide-in/out, auto-dismiss, error/success/info)
- Replaced all `alert()` calls with non-blocking toast notifications
- Button loading states with spinners during async operations
- Prevent double-clicks with disabled state during API calls
- Success feedback toasts for delete and export operations

---

## Phase 11 – Spreadsheet validation ✅

- Validate required columns on upload (`Cat No`, `Title`, `Artist`)
- Clear 400 error with "did you mean?" fuzzy-match suggestions for misspelled columns
- Reject non-Excel, corrupt, and empty files with clear error messages
- Validation warnings for missing optional columns
- Warning for header-only spreadsheets (no data rows)
- 19 new tests for validation logic (172 tests total)

---

## Phase 12 – Artists Index: core pipeline ✅

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

## Phase 13 – Artists Index: overrides & warnings ✅

- Per-artist override CRUD (display name, qualifier, RA status, sort key,
  second artist fields, catalogue number list)
- Exclude / re-include individual artists from export
- Company flag toggle
- Three-state resolved fields in the frontend (original → override → resolved)
- Warning type filter for targeted review
- Enriched flag styling (RA badge, company badge, linked/multi-name indicators)

---

## Phase 14 – Artists Index: export templates ✅

- `IndexExportConfig` with 12 configurable fields
- Separate `index_template` config_type in the Ruleset model
- Index template CRUD API (`/index/templates`)
- Seed template: `index-default.json`
- Combined Templates page in UI (LoW + Index tabs)
- Template editor: paragraph/character styles, toggles, separators

---

## Phase 15 – Artists Index: Letter groups & export ✅

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

## Phase 16 – Permissions & operations parity ✅

- Three-tier role model: Viewer / Editor / Admin (`Role` IntEnum)
- `require_role()` guard on all 8 route modules
- Frontend role-aware UI: viewer sees read-only, editor/admin unlock editing
- Dev role switcher in header (`<select>` + `localStorage` persistence)
- `_apiHeaders()` centralises HTTP headers (API key + role override)
- Audit log parity for Index: `artist_id` FK on AuditLog, enriched API, panel in UI
- Export diff for Index: `save_index_export_snapshot`, `compute_index_diff`,
  `GET /index/imports/{id}/export-diff`, diff panel in frontend
- Re-import for Index: `reimport_index_excel` service matching by `sort_key` + courtesy,
  override/exclusion snapshot+restore, audit log, `PUT /index/imports/{id}/reimport`
- Frontend reimport panel with filename mismatch warning
- Duplicate name merge/unmerge for Index
- Non-ASCII character warnings
- 560 tests total

---

## Phase 17 – AWS deployment & cloud infrastructure ✅

### Storage

- Migrated uploaded Excel files from local Docker volume to **Amazon S3**
- Presigned URLs for upload/download (avoid passing file bytes through the API)
- Configurable bucket name via `S3_BUCKET` / `AWS_REGION` env vars
- Local-disk fallback for development (`STORAGE_BACKEND=local|s3`)

### Compute & networking

- **ECS Fargate** for the FastAPI container — no EC2 management
- **RDS PostgreSQL 16** replacing the Docker Compose Postgres container
- **ALB** (Application Load Balancer) with TLS termination and host-based routing
- Health check endpoint (`/health`) used for ALB target-group probes
- VPC with public/private subnets and security groups

### HTTPS & domains

- ACM certificates for `catalogue.hoy.la` (prod) and `staging-catalogue.hoy.la` (staging)
- HTTPS on port 443 with HTTP→HTTPS redirect
- Host-based routing on ALB for prod and staging
- Staging banner displayed on staging environment

### CI/CD

- **GitHub Actions** pipeline: test → Docker build → push to ECR → deploy to ECS
- Branch-based deployment: non-main branches → staging, main → production
- OIDC federation for keyless AWS authentication from GitHub Actions
- Separate staging and production ECS services
- Alembic migrations run automatically on container startup

### Secrets & configuration

- **AWS Secrets Manager** for `DATABASE_URL` and other secrets
- `.env` file used only for local development

---

## Phase 18 – Cognito authentication & user management ✅

### Authentication

- **Amazon Cognito** user pool replacing single shared API key
- Three-mode auth: Cognito JWT → API key (legacy) → no auth (local dev)
- JWT validation via `PyJWT` (signature, expiry, audience, issuer)
- Cognito groups mapped to application roles (admin > editor > viewer)
- `ContextVar`-based request-scoped user context
- Audit log `user_email` column auto-populated from request context
- Alembic migration for new column

### Frontend auth

- Cognito login form (email + password) with `USER_PASSWORD_AUTH` flow
- `NEW_PASSWORD_REQUIRED` challenge handling (force change on first login)
- Token storage in `sessionStorage` with automatic refresh
- Role badge in header (admin=red, editor=blue, viewer=grey)
- Fallback to legacy API key input when Cognito is not configured

### User management (admin panel)

- Backend: `/users` CRUD routes via boto3 Cognito admin APIs
  (list, create, update role, enable/disable, reset password)
- Frontend: Users section in Settings page (admin-only, Cognito-only)
  with user table, create form, role change dropdown, enable/disable toggle,
  password reset
- IAM: `catalogue-cognito-admin` inline policy on ECS task role
- 577 tests total across 24 test files

---

## Phase 19 – Settings UX & seed template management ✅

### Settings page redesign

- Known Artists section uses card-based layout (one card per artist rule)
- Each card shows a live preview bar with the resolved index-format name
- Three-state resolved fields (original → override → resolved) with
  Clear / Undo controls and colour-coded state indicators
- Company flag toggle dims irrelevant fields (Artist 1 first name, Artist 2)
- Per-section Save buttons: "Save Preview Settings" (everyone, localStorage)
  and "Save Tokens" (admin only, API call) replace the old global Save
- Edition settings (prefix, brackets) grouped below numerical settings
  (currency, thousands, decimals) with visual divider

### Seeded Known Artists

- `is_seeded` Boolean column on `KnownArtist` model (Alembic migration)
- Widened unique constraint to `(match_first, match_last, match_quals, is_seeded)`
  so user copies can coexist with seeded originals
- Seeded entries are read-only in the UI (blue card styling, BUILT-IN badge,
  locked fields, no Save/Delete buttons)
- `POST /{id}/duplicate` endpoint creates a user-editable copy of a seeded entry
- Cache builder prefers user entries over seeded ones during import resolution
- 403 guards prevent API-level edits/deletes on seeded entries

### Seed template JSON export

- `GET /known-artists/export` — admin-only download of all known artists as
  seed-format JSON (alphabetically sorted by last name, first name)
- `GET /templates/{id}/export` — admin-only download of a LoW export template
  as seed-format JSON (with `_name` metadata, filename from slug)
- `GET /index/templates/{id}/export` — admin-only download of an Index export
  template as seed-format JSON (with `_name` and `_config_type` metadata)
- Export JSON buttons on the Settings page (Known Artists) and Templates page
  (per-template row) — admin-only

### Test count

- 683 tests across 28 test files

---

## Phase 20 – Data model symmetry & override form redesign ✅

### Data model symmetry

Known Artists and Overrides now share the same set of overridable fields:

- **`resolved_title`** added to Known Artists (was only on Overrides) — allows
  pre-baking a title (e.g. "Sir") that applies automatically on import
- **`notes`** added to Overrides (was only on Known Artists) — human-readable
  explanation of why an override exists
- **`resolved_company`** / **`company_override`** — explicit company name text
  (overrides the auto-derived `company = last_name` fallback)
- **`resolved_address`** / **`address_override`** — explicit address text
  (overrides the raw `Address 1` column value)

All four fields participate in the 3-layer resolution pipeline:
importer → known artist → user override.

### Company text priority fix

When `is_company` is true and no raw company text exists in the spreadsheet,
the system auto-derives `company = last_name`. This auto-derivation now
correctly yields to explicit company text from known artist (`resolved_company`)
or override (`company_override`).

### Override form redesign

The per-artist override form was redesigned to match the Known Artists card
layout — a 3-column grid with Artist 1 / Artist 2 / Artist 3 sections, each
containing their relevant fields and an RA styled checkbox. The footer
contains the Company checkbox, Company Name, Address, Notes, and action buttons.

### Frontend

- Title field added to Known Artists form (Artist 1 section)
- Company Name and Address fields added to both Known Artists and Override forms
- Notes field added to Override form footer
- Detail table address row shows resolved address

### Test count

- 700 tests across 28 test files (11 new: 7 company/address, 4 title resolution)

---

## Phase 21 – LoW overrides form & template UX ✅

### LoW overrides form

- **Notes field** added to `WorkOverride` model, schema, and API (`notes` column
  via Alembic migration `i9a1b3c5d7e8`)
- **3-column grid layout** for the per-work override form: Content (title,
  medium), Artist (artist, honorifics), Pricing & Edition (price text/numeric,
  edition total/price, artwork). Notes field in footer row. Responsive
  breakpoints at 900px and 600px.
- `model_validate()` refactor: replaced manual `OverrideOut(...)` and
  `WorkOverrideOut(...)` construction with Pydantic `model_validate()`, fixing
  a pre-existing bug where `artwork_override` was missing from section listings.
- `field_validator` on `OverrideOut.work_id` for UUID-to-str coercion.
- Notes preserved on reimport (added to `OVERRIDE_FIELDS` in both LoW and
  Index importers; `company_override` and `address_override` also added to
  Index importer's preservation list).

### Index template UX

- **Entry Layout Examples** section: static annotated examples showing how
  index entries are assembled, with visual conventions, labelled character
  styles, and side-by-side layout.
- Save button repositioned above the Entry Layout Examples section.

### Known Artists UX

- **Dirty tracking**: Save button only enabled when the form has unsaved changes.
- **Duplicate pattern warnings**: inline warning when `match_pattern` duplicates
  an existing known artist.
- **4-column grid layout** for known artist cards.

### Seed template tests

- 10 new tests validating seed template JSON files against expected schemas
  (`tests/test_seed_templates.py`).

### Test count

- 722 tests across 29 test files

---

## Phase 22 – Index rendering correctness & preview ✅

### Character style boundary fix

Character styles in the InDesign Tagged Text export now wrap **only the
meaningful value**, not surrounding separators. Previously, commas and spaces
between styled components were incorrectly included inside `<cstyle:>` tags.

Affected styles: RA surname, RA qualifications, catalogue numbers.

Before: `<cstyle:RA Surname>Ackroyd, <cstyle:>`
After:  `<cstyle:RA Surname>Ackroyd<cstyle:>, `

Applied to: backend renderer, frontend entry preview, Entry Layout Examples.

### Three-artist "and" handling

When an index entry has three artists, only the **last** additional artist
is prefixed with "and". The middle artist is comma-separated:

Before: `Eggerling, Gabriele, and Dhruv Jadhav, and Hannah Puerta-Carlson`
After:  `Eggerling, Gabriele, Dhruv Jadhav, and Hannah Puerta-Carlson`

Two-artist entries remain unchanged (`..., and Second Artist`).

### Tri-state Company checkbox

The "Is Company" checkbox on Known Artists and Override forms now supports
tri-state: null (no override / fall through), true (force company), false
(force non-company). Visual states: empty = null, checked = true,
dash = false.

### Entry preview

The index detail panel now includes a styled entry preview showing the full
rendered line as it would appear in export. Styled segments (RA surname,
quals, honorifics, cat numbers) are colour-coded with tooltips showing the
InDesign character style name.

### Detail table field reorder

Index detail table spreadsheet columns reordered to match the actual
spreadsheet column order: Title → First Name → Last Name → Quals →
Company → Address.

### Per-card save status

Known Artists "Saved" confirmation messages now appear on the specific card
that was saved, rather than in the global status area.

### LoW work detail panel

Clicking a work row now expands an inline detail panel showing the full
data pipeline: Spreadsheet (raw) | Normalised | Override. Same visual
convention as the index detail panel (grey = unchanged, bold black =
changed). Per-work validation warning badges are shown above the table.
The Artwork column is hidden by default with a Settings toggle.

### Warning → detail panel auto-expand (LoW + Index)

Clicking a warning link in the warnings panel now scrolls to the relevant
row **and** automatically opens its detail panel, so the normalisation
context is immediately visible alongside the warning.

### Raw fields in WorkOut API response

Fixed a bug where `raw_title`, `raw_artist`, `raw_price`, `raw_edition`,
`raw_artwork`, and `raw_medium` were always `null` in the `list_sections`
response despite the data existing in the database.

### Test count

- 769 tests across 31 test files

---

## Phase 23 – LoW Flags column, whitespace detection & Compare navigation ✅

### LoW Flags column

Replaced the per-row Include toggle with a **Flags column** showing visual
badges for each work: Override, RA (honorific detected), Norm (value changes),
Trimmed (whitespace-only changes), and validation warning badges. Badges come
from both client-side detection and server-side warnings. The Include/Exclude
toggle moved into the work detail panel.

Excluded works are now displayed with dimmed styling (reduced opacity,
line-through text) and a red ✕ marker on the catalogue number.

### Whitespace trimming detection

Fixed whitespace detection in both LoW and Index: the comparison logic was
trimming both raw and normalised values before comparing, which hid
whitespace-only differences. Now compares untrimmed values first.

Index `_normReasons()` expanded to check all six spreadsheet fields
(Title, First Name, Last Name, Quals, Company, Address) — was only checking
Last Name, First Name, and Quals.

Work detail panel now shows a normalisation explanation listing exactly which
fields were changed and why (whitespace trimming, value changes, honorific
extraction).

### LoW `whitespace_trimmed` validation warning

Added `whitespace_trimmed` as a per-work validation warning in
`collect_work_warnings()`. Checks Title, Artist, and Medium for
whitespace-only differences between raw and normalised values. This matches
the existing Index-level `whitespace_trimmed` warning for consistency.

### Compare page navigation

Artist and work names in the Compare table are now clickable navigation links
that open the corresponding LoW or Index detail page. Links use URL hash
parameters (`?scrollWork=`, `?scrollArtist=`) so Cmd+click / Ctrl+click
opens in a new tab.

### Test count

- 775 tests across 31 test files

---

## Phase 24 – LPG, reconciliation, configurable normalisation & editor redesign ✅

The Large Print Guide (LPG) as a second output of the List of Works data, the
machinery to keep it in sync with last-minute downstream edits, and the editorial
controls and editor UX around it.

- **LOW → LPG reconciliation** — parse a corrected InDesign LOW export back in
  (`low_tag_parser.py`), 2-way diff it against the DB with data-driven
  significance tiers and cosmetic suppression (`low_diff.py`), route findings by
  fix channel, persist uploads as append-only snapshots with live diff recompute.
  Validated against the real 2025 export (1729/1729, 0 findings). See
  [`reconcile.md`](./reconcile.md).
- **LPG output from the shared template model** — `paragraph_style` per component
  lets one template/renderer produce both the single-paragraph LOW and the
  paragraph-styled LPG; per-room (per-section) export with template + gallery-name
  filenames.
- **Title Case Title** — derived `title_cased` field + `title_cased_override`,
  best-effort title-casing with admin-editable acronym/numeral exceptions; the
  LPG uses it while the LOW keeps house caps.
- **Configurable normalisation rules** — edition-suppression threshold, literal
  text substitutions, title-case exceptions (and a fix so the honorific-token
  config actually reaches imports).
- **Entry Layout editor redesign** (from a Claude Design handoff) — character
  styles moved onto each element row, paragraph-block grouping with an
  inline/new-paragraph toggle, and a live sample-entry + Tagged-Text preview.
- Documentation consolidated; the temporary reconciliation roadmap retired into
  permanent docs ([`reconcile.md`](./reconcile.md), `export_spec_v1.md`,
  `architecture_v1.md`).

### Test count

- 900 tests across 37 test files

---

## Phase 25 – Reimport snapshots, diff & undo ✅

Make "Update Import" reversible and transparent after the fact (see
`architecture_v1.md` §5.3).

- **Pre-reimport snapshots** — `ImportSnapshot` model + migration; every real
  re-import captures the full mutable state (append-only, in-transaction,
  whole-import even when gallery-scoped). Full-column serialisation so a new
  field can't silently fall out.
- **Attributed diff** — `diff_states` reports field-level changes tagged by
  cause (source / normalisation / override), fingerprint-first pairing. Surfaced
  as a "What the last update changed" panel on the import detail page.
- **Undo / restore** — `restore_snapshot` reinstates a prior state verbatim
  (original ids, no re-normalisation); itself reversible and audited.
  `POST …/snapshots/{id}/restore` + an editor-only "Undo this update" button.
- **Two fixes surfaced en route** — `title_cased_override` /
  shared-surname overrides were silently dropped on re-import (PR #107, with a
  structural test pinning each preservation list to its model); a text price
  override (`NFS`/`*`) won in export but not in the UI (PR #109).
- *Deferred:* restore does not reinstate the Import record's
  `filename`/`description`.

### Test count

- 1019 tests across 45 test files

---

## Future considerations

- Bidirectional LPG / multi-paragraph LOW reconciliation (parser would map by
  paragraph style and stitch multi-paragraph entries — see the fragility boundary
  in [`reconcile.md`](./reconcile.md))
- **One-off: learn from a corrected Artists Index.** Apply the reconcile insight
  — *diff what humans changed against what the tool produced, then promote the
  systematic corrections upstream into normalisation* — to the Index, as a
  **one-off analysis, not a standing pipeline**. The Index needs no recurring
  reconcile because (unlike the LOW→LPG pair) it has no downstream output to keep
  in sync; the value here is purely the learning. The corrections we'd find are
  the *residual* error after the existing index normalisation (multi-artist split,
  quals extraction, RA detection, company detection, dedupe), so they point
  straight at where those rules fall short. A **null result is itself useful**: if
  corrections are mostly idiosyncratic one-offs, the finding is "don't automate
  the Index further."
  - *Join key:* match corrected ↔ original on each entry's **cat-number set**
    (`index_cat_numbers`), **not the name** — the name is the field being
    corrected, so it's a circular key, whereas an artist's set of works is
    correction-stable. Use set **overlap, not equality**, so merges and splits
    (`duplicate_name_merged`, multi-artist) surface in the partial-overlap
    residue — likely where the richest systematic patterns hide.
  - *Precondition:* a matched pair — raw input **and** a human-corrected index for
    the *same* dataset. Effort depends on the corrected file's form: a spreadsheet
    is a near-trivial column diff; an InDesign export / PDF needs a small parser
    for the published "Lastname, Firstname QUALS … 123, 456" format.
  - *Deliverable:* a throwaway script + short findings doc categorising
    corrections by type, ranked by frequency, splitting systematic (→ a
    normalisation rule) from idiosyncratic (→ leave it). No new infrastructure.
- Per-gallery catalogue-number styles in the LOW template (numerals vs text)
- **House-style pill update.** Make every `.badge` instance pill-shaped
  (`border-radius: 9999px`) for visual consistency between the import-notes
  chips (already pill-shaped) and the row-level flag pills, honorifics pill,
  warning labels, and other badge surfaces (currently `border-radius: 3px`).
  Deferred from the 2026-05-28 Claude Design handoff (PR #74) — the chips were
  made pill-shaped in isolation; doing the same to every other `.badge` is a
  larger blast radius (touches every surface using the primitive) and worth
  doing as its own change with before/after eyeballing.
- Undo / revision history for overrides
- Bulk override import from Excel
- Multi-user conflict resolution (optimistic locking)
- PDF preview generation
- Webhook / notification on import completion

---

## Maintenance backlog

**Medium**

- **Price parsing precision**: preserve `Decimal` precision through
  `parse_price()`, rendering, and tests so cents/decimals are never silently
  truncated by float conversion.

- **Frontend modularity**: `frontend/app.js` is a single large file (~5700
  lines). Consider splitting into modules or adding a minimal bundler step.

**Low**

- **Alembic migration gating**: migrations run at module import time
  (`main.py` line 54). Acceptable for all three environments — Docker
  Compose (local), ECS Fargate (staging/prod) — since the module is only
  imported by Uvicorn on container startup. Would only matter if interactive
  tooling or autogenerate workflows imported `main.py` directly.

- **JWKS caching resilience**: add a TTL or refresh-on-failure strategy for
  Cognito JWKS to handle key rotation without a container restart.

- **Request tracing**: add `X-Request-Id` propagation to logs for easier
  troubleshooting.

- **Sticky-shadow feature dropped 2026-05-30 — unresolved compositing
  mystery.** Pack 03 (2026-05-29) shipped a stuck-shadow under sticky
  section headers via `.is-stuck` (toggled by an IntersectionObserver)
  and a CSS rule `box-shadow: 0 8px 10px -9px rgba(.25)` on either the
  summary or the thead th. Luke flagged the shadow as invisible in
  both Firefox and Chrome during Pack 03 QA. On 2026-05-30 we
  investigated for ~1h:

  Findings (verified via Chrome DevTools driving):
    * IntersectionObserver wiring works; `.is-stuck` is toggled on the
      correct summaries when sentinels cross the viewport top.
    * CSS rule matches: with `.is-stuck` present and the thead pattern,
      the computed `box-shadow` on the thead th is exactly what the
      rule specifies (verified with both subtle and DIAGNOSTIC 60%-red
      values).
    * No `overflow:hidden` anywhere up the ancestor chain.
    * TH is sticky-pinned at `top:71px`, z-index:15, sitting visibly
      above a transparent body. Geometry of where the shadow SHOULD
      paint (~y=96-128 with the diagnostic value) is well inside the
      visible viewport.

  Despite all of the above, even the deliberately-obnoxious 60%-red
  diagnostic shadow did NOT read visibly during real-time inspection.
  Most likely a stacking-context / sticky-compositing subtlety (the
  shadow may be rendering "behind" something invisible to
  `elementsFromPoint` analysis, or paint order between the sticky TH
  and the section.panel siblings is interacting unexpectedly), but
  the time budget for the investigation ran out before we could pin
  it down.

  PR #99 (2026-05-30) removes both shadow CSS rules entirely. The
  sticky pinning itself (summary + thead) works correctly and stays
  -- it's a useful affordance even without the visual "you are stuck"
  cue. The `.is-stuck` class is still toggled by the JS, harmlessly,
  in case a future fix or alternative use wants the hook.

  To revive: the existing JS scaffolding (sentinel + IO + class) is
  intact, so a future attempt only needs to add the CSS rule back and
  diagnose the compositing puzzle in real time. The investigation
  notes above are the head start.

- **Seed loaders never UPSERT changed values on existing rows.** Both
  `seed_known_artists` and `seed_builtin_templates` are insert-if-missing
  only — neither updates the *resolved values* of an existing entry when
  the seed JSON is edited. Edits to a known-artist's `resolved_*` fields
  or to the inner config of a template are silently ignored on every
  existing deployment; the only way to propagate them today is to delete
  the row manually and let the loader re-insert it on restart. Discovered
  during the 2026-05-30 seed-loader audit (the same audit that surfaced
  the `is_seeded` / `resolved_title` / `resolved_company` /
  `resolved_address` field-omission fixes in PR #94). For known-artists
  any future UPSERT must respect the user-row-wins coexistence rule
  already encoded in `build_known_artist_cache` — i.e. UPSERT the seed
  row's own `is_seeded=True` copy only; never touch the
  `is_seeded=False` user customisation. For templates the same applies
  to the `is_builtin=True` row only. Worth a small, dedicated PR
  (probably with another structural test that asserts the UPSERT
  reaches every column the constructor sets).

- **Entry-Layout preview: `final_sep_from_last_component` is invisible.**
  The "If the last element is omitted, use its separator after the final
  non-empty field instead" checkbox in the Entry Layout editor updates the
  template config correctly and the backend export renderer honours it,
  but the live preview pane does not — `renderEntryPreview` ignores the
  setting entirely, so the editor gives no visual feedback that the
  toggle has done anything. Discovered during Pack 04a (2026-05-30) while
  fixing the adjacent missing-re-render bug on the three wrap-options
  handlers. Two viable directions:

  1. *Implement preview-side support.* The renderer would need to inspect
     visible items after filtering, detect when the last enabled component
     was omitted-because-empty, and substitute its `separator_after` after
     the final remaining item. Modest amount of code; matches the export
     renderer's existing logic.
  2. *Mark it as export-only.* Add a small inline hint next to the
     checkbox ("affects export only — not previewable") and leave the
     renderer alone. Lower cost; honest about scope.

  No correctness issue in the export itself — the bug is purely editor
  ergonomics. Currently the user has no way to tell whether the toggle
  is doing what they expect without exporting and inspecting the file.

- **Entry-Layout preview doesn't style RA honorifics separately from the
  artist name.** The actual backend export renderer wraps the artist name
  and the honorifics in two distinct `<CharStyle:…>` runs (using
  `artist_style` and `honorifics_style` respectively), so an export for
  "Sir Anish Kapoor RA" emits something like
  `<CharStyle:Artist>Sir Anish Kapoor<CharStyle:> <CharStyle:Honorifics>RA<CharStyle:>`.
  The Entry-Layout editor's preview (`_tePreviewHTML` → `renderEntryPreview`)
  and the drawer's output preview both concatenate the honorifics into the
  artist string and apply one style, so RA artists look mono-styled when
  they will actually export bi-styled. Pre-existing in the editor; the
  drawer inherits it. Discovered during Pack 04b QA (2026-05-30).

  Fix shape (modest, contained):
  1. Pass `honorifics` as a separate value in `fieldValues` (and add it to
     `_TE_SAMPLES` for the editor).
  2. Add a `honorifics` entry to `_TE_CHAR_KEY` mapped to `honorifics_style`.
  3. Teach `renderEntryPreview` + `renderEntryTaggedText` that when
     emitting the `artist` component's token, also emit a separately-
     styled `honorifics` token after it (space-separated) if
     `fieldValues.honorifics` is present.

  Affects ~25%+ of works in any catalogue (every RA artist). The drawer's
  output-preview pitch — "this is what export will produce" — is
  materially wrong for those. Worth folding into a Pack 04 follow-up or
  taking as its own small PR.

- **Index template editor has no Tagged Text preview tab.** The LoW
  template editor (`renderTemplateEdit` for `list_of_works` templates)
  has two preview tabs: a structural preview and a Tagged Text preview
  showing the actual `<ParaStyle:…>` / `<CharStyle:…>` codes that will
  be written to the export. The Index template editor has only the
  structural preview. Discovered during Pack 04a QA (2026-05-30). Two
  viable directions:

  1. *Build the tab on Index.* `_teTaggedTextHTML`-equivalent for index
     templates exists in spirit (the backend index renderer emits the
     same kind of tagged output), so it's mostly a matter of wiring the
     existing logic into the editor. Symmetry with LoW; helps when
     debugging unexpected styling in the published index.
  2. *Document the asymmetry as deliberate.* The Index output is
     simpler than LoW (no LPG counterpart, fewer character styles per
     entry) and the structural preview already shows what the editor
     needs. Add a short note in the Index template editor explaining
     that the Tagged Text view isn't available because the output
     shape is predictable from the structural preview alone.

  No correctness impact in either case — pure editor ergonomics, and
  Index editors are a small audience.
