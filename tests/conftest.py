# conftest.py
#
# IMPORTANT: The top-level monkey-patch below MUST run before any backend model
# is imported.  pytest loads conftest.py before collecting/importing test
# modules, so this is safe – but do not move it below any backend import.

import sqlalchemy.dialects.postgresql as _pg
from sqlalchemy import types as _sat

# Make JSONB transparent on SQLite (stored as JSON/TEXT)
_pg.JSONB = _sat.JSON
# UUID(as_uuid=True) already degrades gracefully to VARCHAR on SQLite;
# no patch needed for that type.

# --------------------------------------------------------------------------- #

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Import Base *after* the patch so create_all uses the patched column types
from backend.app.db import Base  # noqa: E402

# Ensure every model table is registered on Base.metadata
import backend.app.models.ruleset_model  # noqa: F401
import backend.app.models.import_model  # noqa: F401
import backend.app.models.section_model  # noqa: F401
import backend.app.models.work_model  # noqa: F401
import backend.app.models.override_model  # noqa: F401
import backend.app.models.validation_warning_model  # noqa: F401
import backend.app.models.audit_log_model  # noqa: F401

from backend.app.api.import_routes import router, get_db

SQLITE_URL = "sqlite:///:memory:"


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


@pytest.fixture()
def db_session():
    """
    Each test gets its own isolated in-memory SQLite database.
    Data persists across requests within the test (normal commit behaviour)
    and is discarded completely when the engine is disposed after the test.
    """
    eng = create_engine(
        SQLITE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # single connection ensures create_all and queries share the same in-memory DB
    )
    Base.metadata.create_all(bind=eng)
    _Session = sessionmaker(autocommit=False, autoflush=False, bind=eng)
    session = _Session()

    yield session

    session.close()
    eng.dispose()


@pytest.fixture()
def client(db_session):
    """FastAPI TestClient wired to the test's isolated DB session."""
    app = FastAPI()
    app.include_router(router)

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
