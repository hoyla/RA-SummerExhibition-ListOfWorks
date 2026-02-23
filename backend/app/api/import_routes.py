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
    imports,
    overrides,
    exports,
    templates,
    normalisation_config,
    audit,
    index,
    index_templates,
    known_artists,
)

router = APIRouter(dependencies=[Depends(require_api_key)])

router.include_router(imports.router)
router.include_router(overrides.router)
router.include_router(exports.router)
router.include_router(templates.router)
router.include_router(normalisation_config.router)
router.include_router(audit.router)
router.include_router(index.router)
router.include_router(index_templates.router)
router.include_router(known_artists.router)
