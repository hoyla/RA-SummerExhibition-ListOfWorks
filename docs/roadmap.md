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
- JWT validation via `python-jose` (signature, expiry, audience, issuer)
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

## Future considerations

- Advanced title casing rules (LPG eccentricities)
- Undo / revision history for overrides
- Bulk override import from Excel
- Multi-user conflict resolution (optimistic locking)
- PDF preview generation
- Webhook / notification on import completion
