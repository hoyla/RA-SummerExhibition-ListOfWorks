import logging
import os
import platform
import shutil
import time
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request, Depends
from fastapi.exceptions import ResponseValidationError
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import text

from backend.app.config import LOG_LEVEL, CORS_ORIGINS, API_KEY
from backend.app.db import engine, Base
from backend.app.api.auth import get_current_role, Role

from backend.app.models import import_model
from backend.app.models import section_model
from backend.app.models import work_model
from backend.app.models import override_model
from backend.app.models import ruleset_model
from backend.app.models import validation_warning_model
from backend.app.models import audit_log_model
from backend.app.models import export_snapshot_model
from backend.app.models import index_artist_model
from backend.app.models import index_cat_number_model
from backend.app.models import index_override_model
from backend.app.models import known_artist_model

# ---------------------------------------------------------------------------
# Run Alembic migrations on startup (replaces Base.metadata.create_all)
# ---------------------------------------------------------------------------

from alembic.config import Config as AlembicConfig
from alembic import command as alembic_command
from sqlalchemy import inspect as sa_inspect

_alembic_cfg = AlembicConfig(
    str(Path(__file__).resolve().parent.parent.parent / "alembic.ini")
)

# If the DB already has tables but no alembic_version table, stamp it first
# so that upgrade() doesn't re-create existing tables.
_inspector = sa_inspect(engine)
_has_alembic = "alembic_version" in _inspector.get_table_names()
_has_tables = "imports" in _inspector.get_table_names()
if _has_tables and not _has_alembic:
    alembic_command.stamp(_alembic_cfg, "head")

alembic_command.upgrade(_alembic_cfg, "head")

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

    # Ensure uvicorn loggers propagate to root so that unhandled
    # exceptions logged by Starlette's ServerErrorMiddleware appear
    # in our structured JSON output instead of being silently lost.
    for _name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        _lg = logging.getLogger(_name)
        _lg.handlers.clear()
        _lg.propagate = True


_setup_logging()
logger = logging.getLogger("catalogue")

# Capture startup time for uptime reporting
_start_time = time.monotonic()


# ---------------------------------------------------------------------------
# Seed built-in templates from backend/seed_templates/*.json
# ---------------------------------------------------------------------------

from backend.app.services.seed_service import seed_builtin_templates as _seed_builtin_templates

_seed_builtin_templates()


# ---------------------------------------------------------------------------
# Seed known artists from backend/seed_templates/known-artists.json
# ---------------------------------------------------------------------------


def _seed_known_artists() -> None:
    from backend.app.db import SessionLocal as _SessionLocal
    from backend.app.models.known_artist_model import KnownArtist as _KnownArtist

    _seed_file = (
        Path(__file__).resolve().parent.parent.parent
        / "backend"
        / "seed_templates"
        / "known-artists.json"
    )
    if not _seed_file.exists():
        return

    db = _SessionLocal()
    try:
        with open(_seed_file, encoding="utf-8") as fp:
            entries = json.load(fp)

        added = 0
        for entry in entries:
            match_first = entry.get("match_first_name")
            match_last = entry.get("match_last_name")
            existing = (
                db.query(_KnownArtist)
                .filter(
                    _KnownArtist.match_first_name == match_first,
                    _KnownArtist.match_last_name == match_last,
                    _KnownArtist.match_quals == entry.get("match_quals"),
                )
                .first()
            )
            if existing:
                continue
            db.add(
                _KnownArtist(
                    match_first_name=match_first,
                    match_last_name=match_last,
                    match_quals=entry.get("match_quals"),
                    resolved_first_name=entry.get("resolved_first_name"),
                    resolved_last_name=entry.get("resolved_last_name"),
                    resolved_quals=entry.get("resolved_quals"),
                    resolved_is_company=entry.get("resolved_is_company"),
                    resolved_artist2_first_name=entry.get(
                        "resolved_artist2_first_name"
                    ),
                    resolved_artist2_last_name=entry.get("resolved_artist2_last_name"),
                    resolved_artist2_quals=entry.get("resolved_artist2_quals"),
                    resolved_artist3_first_name=entry.get(
                        "resolved_artist3_first_name"
                    ),
                    resolved_artist3_last_name=entry.get("resolved_artist3_last_name"),
                    resolved_artist3_quals=entry.get("resolved_artist3_quals"),
                    resolved_artist1_ra_styled=entry.get("resolved_artist1_ra_styled"),
                    resolved_artist2_ra_styled=entry.get("resolved_artist2_ra_styled"),
                    resolved_artist3_ra_styled=entry.get("resolved_artist3_ra_styled"),
                    resolved_artist2_shared_surname=entry.get("resolved_artist2_shared_surname"),
                    resolved_artist3_shared_surname=entry.get("resolved_artist3_shared_surname"),
                    notes=entry.get("notes"),
                )
            )
            added += 1
        if added:
            logger.info("Seeded %d known artist(s)", added)
        db.commit()
    except Exception as exc:  # pragma: no cover
        logger.error("Known artists seed error: %s", exc)
        db.rollback()
    finally:
        db.close()


_seed_known_artists()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Catalogue Tool",
    version="1.0.0",
    openapi_tags=[
        {
            "name": "imports",
            "description": "List of Works: upload, reimport, list, delete, sections, preview, warnings, cleanup",
        },
        {
            "name": "overrides",
            "description": "List of Works: per-work editorial overrides and exclude toggle",
        },
        {
            "name": "exports",
            "description": "List of Works: Tagged Text, JSON, XML, CSV exports and export diff",
        },
        {"name": "templates", "description": "List of Works: export template CRUD"},
        {
            "name": "index",
            "description": "Artists' Index: imports, reimport, artists, overrides, warnings, export, diff, unmerge, templates",
        },
        {
            "name": "known-artists",
            "description": "Known Artists lookup rules and seed data",
        },
        {"name": "config", "description": "Global normalisation configuration"},
        {"name": "audit", "description": "Audit log for all mutating operations"},
        {
            "name": "users",
            "description": "User management (Cognito): list, create, update roles, enable/disable",
        },
        {
            "name": "ops",
            "description": "Health check, version, auth config, and current user info",
        },
    ],
)


# ---------------------------------------------------------------------------
# Catch response-serialisation errors that FastAPI/Pydantic would
# otherwise silently turn into bare 500s (with no log entry).
# ---------------------------------------------------------------------------


@app.exception_handler(ResponseValidationError)
async def _response_validation_error(request: Request, exc: ResponseValidationError):
    logger.error(
        "ResponseValidationError on %s %s: %s",
        request.method,
        request.url.path,
        exc.errors(),
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error (response validation)"},
    )


# ---------------------------------------------------------------------------
# CORS middleware (only added when CORS_ORIGINS is configured)
# ---------------------------------------------------------------------------

if CORS_ORIGINS:
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
    )


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
# User-context middleware
# Sets the current_user_email context var so audit log entries are
# automatically attributed to the authenticated user.
# ---------------------------------------------------------------------------

from backend.app.api.user_context import current_user_email
from backend.app.api.auth import get_current_user as _resolve_user


@app.middleware("http")
async def _set_user_context(request: Request, call_next):
    try:
        email = _resolve_user(request)
    except Exception:
        email = "anonymous"
    tok = current_user_email.set(email)
    try:
        return await call_next(request)
    finally:
        current_user_email.reset(tok)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

app.include_router(import_routes.router)


# ---------------------------------------------------------------------------
# Health endpoint (unauthenticated)
# ---------------------------------------------------------------------------


@app.get("/health", tags=["ops"])
def health():
    """Enhanced health check with system, database, and storage diagnostics."""
    result: dict = {
        "status": "ok",
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }

    # ── Database connectivity ──────────────────────────────────────────
    db_info: dict = {"connected": False}
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            db_info["connected"] = True

            # PostgreSQL version
            row = conn.execute(text("SHOW server_version")).fetchone()
            if row:
                db_info["version"] = row[0]

            # Database size
            row = conn.execute(
                text("SELECT pg_size_pretty(pg_database_size(current_database()))")
            ).fetchone()
            if row:
                db_info["database_size"] = row[0]

            # Table row counts (lightweight reltuples estimate)
            rows = conn.execute(
                text(
                    """
                SELECT relname, reltuples::bigint
                FROM pg_class
                WHERE relkind = 'r'
                  AND relnamespace = (
                      SELECT oid FROM pg_namespace WHERE nspname = 'public'
                  )
                ORDER BY relname
            """
                )
            ).fetchall()
            db_info["table_rows"] = {r[0]: r[1] for r in rows}

            # Active connections
            row = conn.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database()"
                )
            ).fetchone()
            if row:
                db_info["active_connections"] = row[0]

    except Exception as exc:
        logger.error("Health check DB error: %s", exc)
        result["status"] = "degraded"

    result["database"] = db_info

    # ── Disk usage ─────────────────────────────────────────────────────
    disk: dict = {}
    try:
        usage = shutil.disk_usage("/")
        disk["total_gb"] = round(usage.total / (1024**3), 1)
        disk["used_gb"] = round(usage.used / (1024**3), 1)
        disk["free_gb"] = round(usage.free / (1024**3), 1)
        disk["used_pct"] = round(usage.used / usage.total * 100, 1)
    except Exception:
        pass

    # Upload directory stats
    from backend.app.services.storage import storage

    disk.update(storage.stats())

    result["disk"] = disk

    # ── Memory (process-level) ─────────────────────────────────────────
    memory: dict = {}
    try:
        import resource

        rusage = resource.getrusage(resource.RUSAGE_SELF)
        # macOS reports in bytes, Linux in kilobytes
        if platform.system() == "Darwin":
            memory["rss_mb"] = round(rusage.ru_maxrss / (1024**2), 1)
        else:
            memory["rss_mb"] = round(rusage.ru_maxrss / 1024, 1)
    except Exception:
        pass

    # System memory (Linux /proc/meminfo or macOS)
    try:
        meminfo_path = Path("/proc/meminfo")
        if meminfo_path.exists():
            data = meminfo_path.read_text()
            for line in data.splitlines():
                if line.startswith("MemTotal:"):
                    memory["system_total_mb"] = int(line.split()[1]) // 1024
                elif line.startswith("MemAvailable:"):
                    memory["system_available_mb"] = int(line.split()[1]) // 1024
    except Exception:
        pass

    if memory:
        result["memory"] = memory

    # ── System info ────────────────────────────────────────────────────
    result["system"] = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "pid": os.getpid(),
        "uptime_seconds": round(time.monotonic() - _start_time, 1),
    }

    code = 200 if db_info["connected"] else 503
    return JSONResponse(content=result, status_code=code)


@app.get("/", tags=["ops"], include_in_schema=False)
def root():
    """Redirect root to the /ui/ frontend."""
    return RedirectResponse(url="/ui/")


# ---------------------------------------------------------------------------
# Version endpoint (unauthenticated) — commit SHA baked into the Docker image
# ---------------------------------------------------------------------------

_GITHUB_REPO = "https://github.com/hoyla/RA-SummerExhibition-ListOfWorks"
_BUILD_COMMIT = os.environ.get("BUILD_COMMIT", "unknown")


@app.get("/version", tags=["ops"])
def version():
    """Return the commit SHA this image was built from."""
    return {
        "commit": _BUILD_COMMIT,
        "repo": _GITHUB_REPO,
    }


@app.get("/auth/config", tags=["ops"])
def auth_config():
    """Public endpoint returning auth configuration for the frontend.

    The frontend checks this at startup to decide whether to show the
    Cognito login flow or the legacy API-key prompt.
    """
    from backend.app.api.auth import _USE_COGNITO
    from backend.app.config import (
        COGNITO_USER_POOL_ID,
        COGNITO_CLIENT_ID,
        COGNITO_REGION,
    )

    if _USE_COGNITO:
        return {
            "mode": "cognito",
            "userPoolId": COGNITO_USER_POOL_ID,
            "clientId": COGNITO_CLIENT_ID,
            "region": COGNITO_REGION,
        }
    return {"mode": "api_key" if API_KEY else "none"}


@app.get("/me", tags=["ops"])
def get_me(
    request: Request,
    role: "Role" = Depends(get_current_role),
):
    """Return the current user's role and email.

    Used by the frontend to show/hide controls based on permissions.
    """
    from backend.app.api.auth import get_current_user as _get_user

    return {"role": role.name, "email": _get_user(request)}


# ---------------------------------------------------------------------------
# Frontend (served last so API routes take precedence)
# ---------------------------------------------------------------------------

_frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend"
app.mount("/ui", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")
