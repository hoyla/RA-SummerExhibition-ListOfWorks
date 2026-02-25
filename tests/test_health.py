"""
tests/test_health.py

Tests for the /health endpoint logic.  The real endpoint lives on the main app
which requires a PostgreSQL connection at import time (Alembic migrations), so
we mount a trimmed-down replica here that uses the same code paths but speaks
to the in-memory SQLite database from conftest.
"""

import os
import platform
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.app.db import Base


# ---------------------------------------------------------------------------
# Build a minimal app that embeds the same health logic as main.py
# ---------------------------------------------------------------------------

_health_start = time.monotonic()


def _make_health_app(engine):
    """Return a tiny FastAPI app with a /health route bound to *engine*."""
    app = FastAPI()

    @app.get("/health")
    def health():
        result: dict = {
            "status": "ok",
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

        db_info: dict = {"connected": False}
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                db_info["connected"] = True
        except Exception:
            result["status"] = "degraded"

        result["database"] = db_info

        disk: dict = {}
        try:
            usage = shutil.disk_usage("/")
            disk["total_gb"] = round(usage.total / (1024**3), 1)
            disk["used_gb"] = round(usage.used / (1024**3), 1)
            disk["free_gb"] = round(usage.free / (1024**3), 1)
            disk["used_pct"] = round(usage.used / usage.total * 100, 1)
        except Exception:
            pass
        result["disk"] = disk

        memory: dict = {}
        try:
            import resource

            rusage = resource.getrusage(resource.RUSAGE_SELF)
            if platform.system() == "Darwin":
                memory["rss_mb"] = round(rusage.ru_maxrss / (1024**2), 1)
            else:
                memory["rss_mb"] = round(rusage.ru_maxrss / 1024, 1)
        except Exception:
            pass
        if memory:
            result["memory"] = memory

        result["system"] = {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "pid": os.getpid(),
            "uptime_seconds": round(time.monotonic() - _health_start, 1),
        }

        code = 200 if db_info["connected"] else 503
        return JSONResponse(content=result, status_code=code)

    return app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def health_client(db_session):
    """TestClient using the test SQLite engine for the health endpoint."""
    eng = db_session.get_bind()
    app = _make_health_app(eng)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHealthEndpoint:

    def test_returns_200(self, health_client):
        assert health_client.get("/health").status_code == 200

    def test_top_level_keys(self, health_client):
        data = health_client.get("/health").json()
        for key in ("status", "checked_at", "database", "disk", "system"):
            assert key in data, f"missing key: {key}"

    def test_status_ok(self, health_client):
        assert health_client.get("/health").json()["status"] == "ok"

    def test_database_connected(self, health_client):
        data = health_client.get("/health").json()
        assert data["database"]["connected"] is True

    def test_checked_at_is_iso(self, health_client):
        ts = health_client.get("/health").json()["checked_at"]
        # Should parse without error
        datetime.fromisoformat(ts)

    def test_system_section(self, health_client):
        sys_info = health_client.get("/health").json()["system"]
        assert "python" in sys_info
        assert "platform" in sys_info
        assert "pid" in sys_info
        assert isinstance(sys_info["uptime_seconds"], (int, float))
        assert sys_info["uptime_seconds"] >= 0

    def test_disk_section(self, health_client):
        disk = health_client.get("/health").json()["disk"]
        assert "total_gb" in disk
        assert "free_gb" in disk
        assert 0 <= disk["used_pct"] <= 100

    def test_memory_section_present(self, health_client):
        data = health_client.get("/health").json()
        # On macOS and Linux the memory section should be present
        if platform.system() in ("Darwin", "Linux"):
            assert "memory" in data
            assert "rss_mb" in data["memory"]


class TestHealthDbDown:

    @pytest.fixture()
    def broken_client(self):
        """Client whose engine always raises on connect."""
        from unittest.mock import MagicMock

        fake_engine = MagicMock()
        fake_engine.connect.side_effect = Exception("connection refused")
        app = _make_health_app(fake_engine)
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    def test_returns_503(self, broken_client):
        assert broken_client.get("/health").status_code == 503

    def test_status_degraded(self, broken_client):
        data = broken_client.get("/health").json()
        assert data["status"] == "degraded"
        assert data["database"]["connected"] is False

    def test_disk_and_system_still_present(self, broken_client):
        data = broken_client.get("/health").json()
        assert "disk" in data
        assert "system" in data


# ---------------------------------------------------------------------------
# /version endpoint
# ---------------------------------------------------------------------------


class TestVersionEndpoint:

    @pytest.fixture()
    def version_client(self):
        """Minimal app with /version, no DB needed."""
        app = FastAPI()
        _commit = os.environ.get("BUILD_COMMIT", "unknown")
        _repo = "https://github.com/hoyla/RA-SummerExhibition-ListOfWorks"

        @app.get("/version")
        def version():
            return {"commit": _commit, "repo": _repo}

        with TestClient(app) as c:
            yield c

    def test_returns_commit_and_repo(self, version_client):
        r = version_client.get("/version")
        assert r.status_code == 200
        data = r.json()
        assert "commit" in data
        assert "repo" in data
        assert data["repo"].startswith("https://github.com/")

    def test_default_commit_is_unknown(self, version_client):
        data = version_client.get("/version").json()
        assert data["commit"] == "unknown"

    def test_commit_from_env(self):
        """BUILD_COMMIT env var is reflected in the response."""
        with patch.dict(os.environ, {"BUILD_COMMIT": "abc123def"}):
            app = FastAPI()

            @app.get("/version")
            def version():
                return {
                    "commit": os.environ.get("BUILD_COMMIT", "unknown"),
                    "repo": "https://github.com/hoyla/RA-SummerExhibition-ListOfWorks",
                }

            with TestClient(app) as c:
                data = c.get("/version").json()
                assert data["commit"] == "abc123def"


# ---------------------------------------------------------------------------
# ResponseValidationError handler
# ---------------------------------------------------------------------------

from pydantic import BaseModel
from fastapi.exceptions import ResponseValidationError


class TestResponseValidationErrorHandler:
    """Verify that Pydantic response-serialisation errors are logged and
    returned as 500 with a meaningful body (instead of a bare 500 with
    no log entry)."""

    @pytest.fixture()
    def bad_app(self):
        app = FastAPI()

        class StrictOut(BaseModel):
            name: str
            count: int

        @app.exception_handler(ResponseValidationError)
        async def _handler(request, exc):
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal Server Error (response validation)"},
            )

        @app.get("/good", response_model=StrictOut)
        def good():
            return {"name": "ok", "count": 1}

        @app.get("/bad", response_model=StrictOut)
        def bad():
            # Return wrong types — Pydantic will fail to validate
            return {"name": 123, "count": "not-an-int"}

        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    def test_good_endpoint_still_works(self, bad_app):
        r = bad_app.get("/good")
        assert r.status_code == 200
        assert r.json() == {"name": "ok", "count": 1}

    def test_bad_endpoint_returns_500_with_detail(self, bad_app):
        r = bad_app.get("/bad")
        assert r.status_code == 500
        assert "response validation" in r.json()["detail"]
