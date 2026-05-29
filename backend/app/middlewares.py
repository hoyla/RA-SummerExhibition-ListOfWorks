"""Standalone HTTP middlewares.

Defined here rather than inline in ``main.py`` so tests can import and
exercise them without triggering ``main.py``'s startup side-effects
(``alembic upgrade``, seed-template loader).
"""

import logging

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("catalogue")


def make_body_size_limit_middleware(limit_bytes: int):
    """Return a Starlette HTTP middleware that rejects requests whose declared
    ``Content-Length`` exceeds ``limit_bytes`` with a 413 response.

    Doesn't apply to chunked transfers (no ``Content-Length`` header); those
    fall through to whatever Starlette's body parser does. The intent is to
    catch fat-fingered accidental uploads, not to be a perimeter defence.
    """

    async def _limit_request_body(request: Request, call_next):
        declared = request.headers.get("content-length")
        if declared is not None:
            try:
                size = int(declared)
            except ValueError:
                size = 0
            if size > limit_bytes:
                logger.warning(
                    "rejected oversized request: %s %s (%d bytes > %d limit)",
                    request.method,
                    request.url.path,
                    size,
                    limit_bytes,
                )
                return JSONResponse(
                    status_code=413,
                    content={
                        "detail": (
                            f"Request body too large: {size} bytes exceeds "
                            f"the {limit_bytes}-byte limit"
                        )
                    },
                )
        return await call_next(request)

    return _limit_request_body
