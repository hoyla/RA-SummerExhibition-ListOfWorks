"""
Aggregation module — assembles sub-routers into a single authenticated router.

This module exists for backward compatibility.  ``main.py`` and the test suite
import ``router`` and ``get_db`` from here; the actual route handlers now live
in dedicated modules under ``backend/app/api/``.
"""

from fastapi import APIRouter, Depends

from backend.app.api.auth import require_api_key
from backend.app.api.deps import get_db  # noqa: F401  re-exported for tests
from backend.app.api import (
    low_imports,
    low_overrides,
    low_exports,
    low_templates,
    normalisation_config,
    audit,
    index,
    index_templates,
    known_artists,
    users,
    compare,
)

router = APIRouter(dependencies=[Depends(require_api_key)])

router.include_router(low_imports.router)
router.include_router(low_overrides.router)
router.include_router(low_exports.router)
router.include_router(low_templates.router)
router.include_router(normalisation_config.router)
router.include_router(audit.router)
router.include_router(index.router)
router.include_router(index_templates.router)
router.include_router(known_artists.router)
router.include_router(users.router)
router.include_router(compare.router)
