# Developer guide

Operational reference for working on the Catalogue Tool. For architecture
details see [architecture_v1.md](architecture_v1.md).

---

## Local development

Local development uses **Docker Compose** — the app runs inside a container
alongside a PostgreSQL 16 instance.

### First-time setup

```bash
cp .env.example .env          # edit if you want different passwords
docker compose up -d           # starts both db and app containers
open http://localhost:8000/ui   # UI is served by the app container
```

### Day-to-day commands

| Task                         | Command                                         |
| ---------------------------- | ----------------------------------------------- |
| Start the app                | `docker compose up -d app`                      |
| Rebuild after code changes   | `docker compose up -d --build app`              |
| View logs                    | `docker compose logs app --tail=50`             |
| Follow logs live             | `docker compose logs app -f`                    |
| Stop everything              | `docker compose down`                           |
| Stop and **delete all data** | `docker compose down -v` (removes DB + uploads) |

### Important notes

- **Never run `python backend/app/main.py` directly** — the app requires the
  Dockerised PostgreSQL and the container's `UPLOAD_DIR` setup.
- Uploaded files are stored in a **Docker named volume** (`uploads`), not in the
  workspace `uploads/` folder. They persist across rebuilds but are deleted by
  `docker compose down -v`.
- Database data is in a named volume (`pgdata`), same lifecycle.
- Alembic migrations run **automatically on container startup** — no manual
  `alembic upgrade head` needed.
- The local environment has **no authentication** by default (no Cognito, no
  API key). The UI shows an "admin" role with full access.

---

## Running tests

Tests run against an **in-memory SQLite database** — no Docker required.

```bash
# One-time: create venv and install dependencies
python -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt

# Run all 617 tests
python -m pytest tests/ -q

# Run a single test file
python -m pytest tests/test_normalisation.py -q

# Run with verbose output
python -m pytest tests/ -v

# Stop on first failure
python -m pytest tests/ -x
```

If you see `ModuleNotFoundError` when running tests, re-run:

```bash
pip install -r requirements-dev.txt
```

---

## Database migrations (Alembic)

### When to create a migration

**Every time you add, remove, or change a column in a SQLAlchemy model**, you
must create a corresponding Alembic migration. The model change alone does NOT
alter the database.

Checklist:

1. Edit the model in `backend/app/models/`
2. Create a new migration file in `backend/alembic/versions/`
3. Test locally: `docker compose up -d --build app` (migration runs on startup)
4. Check logs: `docker compose logs app --tail=20` — look for
   `Running upgrade ... → ...`
5. Run tests: `python -m pytest tests/ -x -q`

### Migration file template

```python
"""Short description of what changed

Revision ID: <unique_hex_id>
Revises: <previous_revision_id>
Create Date: YYYY-MM-DD
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "<unique_hex_id>"
down_revision: Union[str, Sequence[str], None] = "<previous_revision_id>"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column("table_name", sa.Column("new_col", sa.Text(), nullable=True))

def downgrade() -> None:
    op.drop_column("table_name", "new_col")
```

The `down_revision` must point to the **latest existing** migration. Check with:

```bash
ls backend/alembic/versions/ | sort
```

### How migrations run

- **Locally**: automatically on Docker container startup (`main.py` calls
  `alembic upgrade head`)
- **Staging/Prod**: automatically when the new ECS task starts after CI/CD
  deploy

---

## Environments

| Environment    | URL                        | Database                  | File storage                 | Deployed by                 |
| -------------- | -------------------------- | ------------------------- | ---------------------------- | --------------------------- |
| **Local**      | `localhost:8000`           | Docker PostgreSQL         | Docker volume (`uploads`)    | `docker compose up`         |
| **Staging**    | `staging-catalogue.hoy.la` | RDS (`catalogue-staging`) | S3 (`catalogue-staging-...`) | Push to any non-main branch |
| **Production** | `catalogue.hoy.la`         | RDS (`catalogue-prod`)    | S3 (`catalogue-prod-...`)    | Push/merge to `main`        |

### CI/CD pipeline (GitHub Actions)

Every push triggers:

1. **Test** — runs `pytest` against the full test suite
2. **Build** — builds Docker image, pushes to ECR
3. **Deploy staging** — updates ECS service `catalogue-staging` (non-main branches)
4. **Deploy production** — updates ECS service `catalogue-prod` (main branch only)

AWS resources use **per-environment secrets** in AWS Secrets Manager:

- `catalogue-staging/DATABASE_URL`, `catalogue-staging/API_KEY`, `catalogue-staging/S3_BUCKET`
- `catalogue-prod/DATABASE_URL`, `catalogue-prod/API_KEY`, `catalogue-prod/S3_BUCKET`

---

## Error handling

- **LoW upload errors** are caught and returned as 400 responses.
- **Index upload errors** are caught and logged; `IndexImportError` → 400,
  other exceptions → 500 with detail logged to stdout.
- If an upload returns 500 with no log output, check for unhandled exceptions
  in the route handler — FastAPI's ServerErrorMiddleware swallows these before
  the logging middleware runs.

---

## Key conventions

- **Raw data is immutable** — the raw columns on Import/Work/IndexArtist are
  never modified after import.
- **Normalisation is deterministic** — same input always produces same output.
- **Overrides are separate** — editorial changes are stored in override tables,
  never patched into the raw or normalised layer.
- **Seed templates** — JSON files in `backend/seed_templates/` are upserted on
  startup. The app compares config hashes and only writes when content changes.
- **Tests use SQLite** — the test suite runs entirely in-memory with no external
  dependencies.

---

## Common pitfalls

| Mistake                                          | Prevention                                                 |
| ------------------------------------------------ | ---------------------------------------------------------- |
| Changed a model but forgot the Alembic migration | Always create a migration when changing model columns      |
| Ran the app with `python` instead of Docker      | Use `docker compose up -d --build app`                     |
| Tests fail with `ModuleNotFoundError`            | Run `pip install -r requirements-dev.txt`                  |
| Upload returns 500 but no logs appear            | Check the route handler has a catch-all `except Exception` |
| `docker compose down -v` deleted my test data    | Only use `-v` when you want a fresh start                  |
| Staging not updating after push                  | Check the GitHub Actions run completed successfully        |
