# Catalogue Tool – Requirements

## 1. System Overview

The Catalogue Tool is a backend system for ingesting structured Excel exhibition data and generating structured outputs for editorial review and InDesign production workflows.

The system must:

- Preserve raw source data.
- Apply deterministic normalisation rules.
- Maintain structural integrity of sections and works.
- Provide structured inspection endpoints.
- Generate clean, import-ready InDesign Tagged Text exports.

---

## 2. Functional Requirements

### 2.1 Importing

1. The system must accept Excel file uploads via API.
2. Each upload must create a new immutable Import record.
3. The original filename must be stored.
4. The upload timestamp must be recorded.
5. All raw column values must be preserved exactly as received.

---

### 2.2 Data Structure

The system must model:

Import → Section → Work

Each Import:

- Has many Sections
- Has many Works (via Sections)

Each Section:

- Belongs to one Import
- Has a stable position ordering

Each Work:

- Belongs to one Section
- Has a stable position within that Section

---

### 2.3 Normalisation

The system must normalise the following fields deterministically:

#### Artist

- Trim leading/trailing whitespace.
- Separate name and honorifics where possible.
- Preserve diacritics.
- Preserve punctuation.

#### Price

- Parse numeric prices into decimal values.
- Preserve text values such as:
  - "NFS"
  - "\*"
- Treat blank price fields as "\*".
- Store both numeric and text representations where applicable.

#### Edition

- Parse patterns such as:
  - "Edition of 6 at £3,900.00"
  - "Edition of 27"
- Extract:
  - edition_total
  - edition_price_numeric (if present)
- Suppress meaningless entries such as:
  - "Edition of 0 at £0.00"
  - "Edition of 0 at "
- Treat incomplete price values as unpriced editions.

#### Medium

- Trim whitespace.
- Remove trailing line breaks.
- Preserve descriptive content.

---

### 2.4 API Endpoints

The system must provide:

- POST /import
- GET /imports
- GET /imports/{id}/sections
- GET /imports/{id}/preview
- GET /imports/{id}/export-tags
- DELETE /imports/{id}

---

### 2.5 Export

The system must generate InDesign Tagged Text with:

- Correct paragraph styles.
- Real tab characters.
- Real line breaks.
- UTF-8 encoding.
- No escaped control characters.
- Clean separation between sections.

Export rules must follow the documented export specification.

---

## 3. Non-Functional Requirements

- Deterministic parsing.
- No silent mutation of raw fields.
- UTF-8 safe.
- PostgreSQL-backed.
- REST API compliant.
- Versionable export specification.
- Cascade-safe deletion.
- Stable ordering guarantees.

---

## 4. Data Requirements

- UUID primary keys.
- Cascading deletes on Import.
- Unique (section_id, position_in_section).
- Import immutability (no mutation after creation).

---

## 5. Constraints

- Excel structure must match expected column schema.
- No UI in v1.
- Single-user system (initially).
- No inline formatting logic inside export layer.

---

## 6. Assumptions

- Editorial team controls Excel structure.
- InDesign uses Tagged Text import workflow.
- Exhibition structure is strictly hierarchical.
- Export formatting rules may evolve per exhibition but must remain versioned.

---

## 7. Future Extensions

- Rulesets table for exhibition-specific logic.
- Work override system.
- Validation warnings.
- Audit logging.
- Multiple export formats.
- Authentication and role control.
