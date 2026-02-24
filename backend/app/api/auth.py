"""
Authentication and role-based access control.

Supports three modes (in priority order):

1. **Cognito JWT** – when ``COGNITO_USER_POOL_ID`` is set, requests must carry
   a valid Cognito ID token in the ``Authorization: Bearer <token>`` header.
   The user's role is derived from Cognito groups (admin > editor > viewer).

2. **Shared API key** (legacy) – when only ``API_KEY`` is set, all requests
   must send the key in the ``X-Api-Key`` header.  Role comes from the
   ``X-User-Role`` header (default: viewer).

3. **No auth** – when neither is configured, auth is disabled and the role
   defaults to ``admin``.  This is the local-dev experience.

Public interface:
    - ``require_api_key``   – authentication dependency
    - ``get_current_role``  – resolves the caller's ``Role``
    - ``get_current_user``  – resolves the caller's email (or "anonymous")
    - ``require_role(min)`` – authorization dependency factory
    - ``Role``              – IntEnum (viewer=1, editor=2, admin=3)
"""

from __future__ import annotations

import json
import logging
import urllib.request
from enum import IntEnum
from functools import lru_cache
from typing import Optional

from fastapi import Header, HTTPException, Request, status, Depends
from jose import JWTError, jwt

from backend.app.config import (
    API_KEY,
    COGNITO_USER_POOL_ID,
    COGNITO_CLIENT_ID,
    COGNITO_REGION,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Roles – ordered by privilege level (higher = more powerful)
# ---------------------------------------------------------------------------


class Role(IntEnum):
    viewer = 1
    editor = 2
    admin = 3


_ROLE_NAMES = {r.name for r in Role}

# ---------------------------------------------------------------------------
# Cognito JWKS (cached once per process)
# ---------------------------------------------------------------------------

_USE_COGNITO = bool(COGNITO_USER_POOL_ID)


@lru_cache(maxsize=1)
def _get_jwks() -> dict:
    """Fetch and cache the Cognito JWKS (JSON Web Key Set)."""
    url = (
        f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/"
        f"{COGNITO_USER_POOL_ID}/.well-known/jwks.json"
    )
    with urllib.request.urlopen(url, timeout=5) as resp:
        return json.loads(resp.read())


def _decode_cognito_token(token: str) -> dict:
    """Validate and decode a Cognito ID token.

    Returns the full claims dict on success; raises HTTPException on failure.
    """
    try:
        jwks = _get_jwks()
    except Exception as exc:
        logger.error("Failed to fetch Cognito JWKS: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable",
        )

    # Extract the key ID from the token header
    try:
        unverified_header = jwt.get_unverified_header(token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    kid = unverified_header.get("kid")
    key = None
    for k in jwks.get("keys", []):
        if k["kid"] == kid:
            key = k
            break
    if key is None:
        # Force JWKS refresh in case keys were rotated
        _get_jwks.cache_clear()
        try:
            jwks = _get_jwks()
        except Exception:
            pass
        for k in jwks.get("keys", []):
            if k["kid"] == kid:
                key = k
                break
    if key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token signing key not found",
        )

    issuer = (
        f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/" f"{COGNITO_USER_POOL_ID}"
    )

    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=COGNITO_CLIENT_ID,
            issuer=issuer,
        )
    except JWTError as exc:
        logger.warning("JWT validation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    return claims


# ---------------------------------------------------------------------------
# Shared internal: extract claims from a request
# ---------------------------------------------------------------------------


def _extract_claims(request: Request) -> Optional[dict]:
    """Return decoded JWT claims if Cognito mode is active, else None.

    Stores claims on ``request.state`` so we only decode once per request.
    """
    if not _USE_COGNITO:
        return None

    cached = getattr(request.state, "cognito_claims", None)
    if cached is not None:
        return cached

    auth_header: str = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = auth_header[7:]  # strip "Bearer "
    claims = _decode_cognito_token(token)
    request.state.cognito_claims = claims
    return claims


# ---------------------------------------------------------------------------
# Authentication dependency
# ---------------------------------------------------------------------------


async def require_api_key(
    request: Request,
    x_api_key: str = Header(default=""),
) -> None:
    """Authenticate the request.

    - Cognito mode:  validates the Bearer JWT.
    - API-key mode:  checks ``X-Api-Key`` header.
    - No-auth mode:  passes through.
    """
    if _USE_COGNITO:
        _extract_claims(request)  # raises on failure
        return

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


def get_current_role(request: Request, x_user_role: str = Header(default="")) -> Role:
    """Resolve the current user's role.

    - Cognito mode:  highest-privilege group from the token's
      ``cognito:groups`` claim.
    - API-key mode:  ``X-User-Role`` header (default: viewer in prod,
      admin in dev).
    - No-auth mode:  always admin.
    """
    if _USE_COGNITO:
        claims = _extract_claims(request)
        groups = set(claims.get("cognito:groups", []))
        if "admin" in groups:
            return Role.admin
        if "editor" in groups:
            return Role.editor
        return Role.viewer

    # Legacy API-key path
    if not x_user_role:
        return Role.admin if not API_KEY else Role.viewer

    name = x_user_role.strip().lower()
    if name not in _ROLE_NAMES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role: {x_user_role!r}. Must be one of: {', '.join(sorted(_ROLE_NAMES))}",
        )
    return Role[name]


# ---------------------------------------------------------------------------
# User identity resolution
# ---------------------------------------------------------------------------


def get_current_user(request: Request) -> str:
    """Return the email (or username) of the current user.

    - Cognito mode: ``email`` claim from the JWT.
    - Legacy / no-auth: ``"anonymous"``.
    """
    if _USE_COGNITO:
        claims = _extract_claims(request)
        return claims.get("email") or claims.get("cognito:username", "unknown")
    return "anonymous"


# ---------------------------------------------------------------------------
# Role-based access dependency factory
# ---------------------------------------------------------------------------


def require_role(minimum: str):
    """Return a FastAPI dependency that requires at least the given role.

    Usage::

        @router.post("/things", dependencies=[Depends(require_role("editor"))])
    """
    min_role = Role[minimum]

    async def _check(
        request: Request,
        role: Role = Depends(get_current_role),
    ) -> None:
        if role < min_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires {minimum} role or above",
            )

    return _check
