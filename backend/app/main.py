import logging
import time
import json
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
