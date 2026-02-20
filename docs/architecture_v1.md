# Catalogue Tool – Architecture v1

## 1. System Overview

The Catalogue Tool is a backend service designed to:

1. Ingest structured Excel exhibition data.
2. Preserve raw source values.
3. Apply deterministic normalisation.
4. Provide structured API inspection.
5. Generate clean InDesign Tagged Text exports.

The system is backend-first and editorially deterministic.

---

## 2. High-Level Architecture

Excel Upload  
→ Import Record (immutable)  
→ Sections  
→ Works (raw + normalised fields)  
→ Export Layer

---

## 3. Technology Stack

- Python 3.12
- FastAPI
- SQLAlchemy
- PostgreSQL
- Uvicorn
- Pydantic v2

---

## 4. Data Model

### Import

Represents one uploaded Excel file.

- id (UUID)
- filename
- uploaded_at
- notes

Immutable after creation.

---

### Section

Represents a gallery/room.

- id
- import_id
- name
- position

Ordering guaranteed by `(import_id, position)`.

---

### Work

Represents one catalogue entry.

Raw fields:

- raw_title
- raw_artist
- raw_price
- raw_edition
- raw_medium

Normalised fields:

- title
- artist_name
- artist_honorifics
- price_numeric
- price_text
- edition_total
- edition_price_numeric
- medium

Ordering guaranteed by `(section_id, position_in_section)`.

---

## 5. Normalisation Layer

Located in:

backend/app/services/normalisation_service.py

Principles:

- Deterministic
- Idempotent
- Raw data never mutated
- Unicode safe

---

## 6. Export Layer

Responsible for:

- InDesign Tagged Text generation
- Paragraph style tokens
- Real tab characters
- CR line endings
- UTF-8 output

Export logic must not contain parsing logic.

---

## 7. Design Principles

- Raw data is sacred
- Parsing must be reversible
- Structure over presentation
- Separation of concerns
- Versionable export rules

---

## 8. Extension Points

- Ruleset abstraction
- Editorial override engine
- Validation warnings
- Multi-format export
- UI layer
