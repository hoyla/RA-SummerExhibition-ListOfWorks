"""
API key authentication dependency.

Usage in a route:
    from backend.app.api.auth import require_api_key
    @router.get("/my-route", dependencies=[Depends(require_api_key)])

If the API_KEY environment variable is empty, authentication is disabled so
local development works without any configuration.
"""

from fastapi import Header, HTTPException, status, Depends
from backend.app.config import API_KEY


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
