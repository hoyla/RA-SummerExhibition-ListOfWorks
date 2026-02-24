"""
API key authentication and role-based access control.

Usage in a route:
    from backend.app.api.auth import require_api_key, require_role

    # Any authenticated user:
    @router.get("/things", dependencies=[Depends(require_api_key)])

    # Editor or above:
    @router.post("/things", dependencies=[Depends(require_role("editor"))])

    # Admin only:
    @router.delete("/things", dependencies=[Depends(require_role("admin"))])

If the API_KEY environment variable is empty, authentication is disabled so
local development works without any configuration.

The current user role is determined by the X-User-Role header.  When auth
is disabled (local dev) the role defaults to ``admin`` so all features are
available.  In production the role will come from a Cognito JWT claim.
"""

from enum import IntEnum
from fastapi import Header, HTTPException, status, Depends, Request
from backend.app.config import API_KEY


# ---------------------------------------------------------------------------
# Roles – ordered by privilege level (higher = more powerful)
# ---------------------------------------------------------------------------


class Role(IntEnum):
    viewer = 1
    editor = 2
    admin = 3


_ROLE_NAMES = {r.name for r in Role}


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


async def require_api_key(x_api_key: str = Header(default="")) -> None:
    """Raise 401 if the request does not carry the correct API key.

    Authentication is skipped entirely when API_KEY is not configured,
    which makes local development zero-friction.
    """
    if not API_KEY:
        return  # Auth disabled in development

    if x_api_key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )


# ---------------------------------------------------------------------------
# Role resolution
# ---------------------------------------------------------------------------


def get_current_role(x_user_role: str = Header(default="")) -> Role:
    """Resolve the current user's role.

    When auth is disabled (no API_KEY configured) and no role header is
    sent, defaults to ``admin`` for zero-friction local development.

    In production, this will be replaced by reading the role from a
    Cognito JWT token.
    """
    if not x_user_role:
        # Default: admin in dev, viewer in production
        return Role.admin if not API_KEY else Role.viewer

    name = x_user_role.strip().lower()
    if name not in _ROLE_NAMES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role: {x_user_role!r}. Must be one of: {', '.join(sorted(_ROLE_NAMES))}",
        )
    return Role[name]


# ---------------------------------------------------------------------------
# Role-based access dependency factory
# ---------------------------------------------------------------------------


def require_role(minimum: str):
    """Return a FastAPI dependency that requires at least the given role.

    Usage::

        @router.post("/things", dependencies=[Depends(require_role("editor"))])
    """
    min_role = Role[minimum]

    async def _check(role: Role = Depends(get_current_role)) -> None:
        if role < min_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires {minimum} role or above",
            )

    return _check
