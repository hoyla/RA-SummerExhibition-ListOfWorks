import logging
import time
import json
import hashlib
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from sqlalchemy import text

from backend.app.config import LOG_LEVEL
from backend.app.db import engine, Base

from backend.app.models import import_model
from backend.app.models import section_model
from backend.app.models import work_model
from backend.app.models import override_model
from backend.app.models import ruleset_model
from backend.app.models import export_model
from backend.app.models import validation_warning_model
from backend.app.models import audit_log_model

# Create all tables on startup (must be after all model imports)
Base.metadata.create_all(bind=engine)

# ---------------------------------------------------------------------------
# Schema migrations (add columns that didn't exist at initial deployment)
# ---------------------------------------------------------------------------

from sqlalchemy import text as _sql_text  # noqa: E402

with engine.connect() as _conn:
    _conn.execute(
        _sql_text(
            "ALTER TABLE rulesets ADD COLUMN IF NOT EXISTS config_type TEXT NOT NULL DEFAULT 'template'"
        )
    )
    _conn.execute(
        _sql_text(
            "ALTER TABLE rulesets ADD COLUMN IF NOT EXISTS is_builtin BOOLEAN NOT NULL DEFAULT false"
        )
    )
    _conn.execute(_sql_text("ALTER TABLE rulesets ADD COLUMN IF NOT EXISTS slug TEXT"))
    # Migrate: rename legacy 'active' rulesets to 'Default' so they appear as templates
    _conn.execute(
        _sql_text(
            "UPDATE rulesets SET name = 'Default' WHERE name = 'active' AND config_type = 'template'"
        )
    )
    _conn.commit()

from backend.app.api import import_routes


# ---------------------------------------------------------------------------
# Structured JSON logging
# ---------------------------------------------------------------------------


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _setup_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    if LOG_LEVEL != "DEBUG":
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


_setup_logging()
logger = logging.getLogger("catalogue")


# ---------------------------------------------------------------------------
# Seed built-in templates from backend/seed_templates/*.json
# ---------------------------------------------------------------------------


def _seed_builtin_templates() -> None:
    from backend.app.db import SessionLocal as _SessionLocal
    from backend.app.models.ruleset_model import Ruleset as _Ruleset

    _seed_dir = (
        Path(__file__).resolve().parent.parent.parent / "backend" / "seed_templates"
    )
    if not _seed_dir.exists():
        return

    db = _SessionLocal()
    try:
        for f in sorted(_seed_dir.glob("*.json")):
            slug = f.stem
            with open(f, encoding="utf-8") as fp:
                seed = json.load(fp)
            name = seed.pop("_name", slug)
            cfg_hash = hashlib.sha256(
                json.dumps(seed, sort_keys=True).encode()
            ).hexdigest()
            existing = db.query(_Ruleset).filter(_Ruleset.slug == slug).first()
            if existing:
                if existing.config_hash != cfg_hash:
                    existing.name = name
                    existing.config = seed
                    existing.config_hash = cfg_hash
                continue
            db.add(
                _Ruleset(
                    name=name,
                    config=seed,
                    config_hash=cfg_hash,
                    config_type="template",
                    is_builtin=True,
                    slug=slug,
                )
            )
        db.commit()
    except Exception as exc:  # pragma: no cover
        logger.error("Seed error: %s", exc)
        db.rollback()
    finally:
        db.close()


_seed_builtin_templates()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Catalogue Tool", version="1.0.0")


# ---------------------------------------------------------------------------
# Request logging middleware
# ---------------------------------------------------------------------------


@app.middleware("http")
async def _log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 1)
    logger.info(
        "%s %s %s %.1fms",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

app.include_router(import_routes.router)


# ---------------------------------------------------------------------------
# Health endpoint (unauthenticated)
# ---------------------------------------------------------------------------


@app.get("/health", tags=["ops"])
def health():
    """Lightweight health check. Returns DB connectivity status."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception as exc:
        logger.error("Health check DB error: %s", exc)
        db_ok = False

    payload = {"status": "ok" if db_ok else "degraded", "db": db_ok}
    code = 200 if db_ok else 503
    return JSONResponse(content=payload, status_code=code)


@app.get("/", tags=["ops"])
def root():
    return {"status": "Catalogue tool running"}


# ---------------------------------------------------------------------------
# Frontend (served last so API routes take precedence)
# ---------------------------------------------------------------------------

_frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend"
app.mount("/ui", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")
