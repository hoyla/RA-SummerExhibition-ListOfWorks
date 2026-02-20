# Catalogue Tool

A backend system for ingesting exhibition catalogue Excel files and generating structured exports for editorial and InDesign workflows.

---

## Features

- Excel upload
- Structured import model
- Data normalisation
- API inspection
- InDesign Tagged Text export
- Import deletion

---

## Tech Stack

- Python 3.12
- FastAPI
- SQLAlchemy
- PostgreSQL
- Uvicorn

---

## Quick Start

### 1. Install dependencies

Create virtual environment and install packages.

### 2. Run server

uvicorn backend.app.main:app --reload

### 3. Open API docs

http://127.0.0.1:8000/docs

---

## Typical Workflow

1. Upload Excel file via POST /import
2. Inspect via GET /imports
3. Preview via GET /imports/{id}/preview
4. Export via GET /imports/{id}/export-tags

---

## Project Structure

backend/app/

- api/
- models/
- services/
- db.py
- main.py

docs/

- architecture_v1.md
- roadmap.md
- export_spec_v1.md

---

## Philosophy

- Preserve raw data
- Apply deterministic normalisation
- Keep exports simple
- Separate parsing from presentation
