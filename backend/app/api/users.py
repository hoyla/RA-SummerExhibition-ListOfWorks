"""
User management routes (admin-only).

Provides CRUD operations for Cognito users via the AWS SDK.
Only available when Cognito auth is active.
"""

import logging
from typing import Optional

import boto3
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr

from backend.app.api.auth import require_role, Role
from backend.app.config import COGNITO_USER_POOL_ID, COGNITO_REGION

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(require_role("admin"))],
)

_GROUPS = ["admin", "editor", "viewer"]


def _cognito_client():
    """Return a Cognito IDP client."""
    if not COGNITO_USER_POOL_ID:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="User management requires Cognito authentication",
        )
    return boto3.client("cognito-idp", region_name=COGNITO_REGION)


def _get_user_groups(client, username: str) -> list[str]:
    """Return the list of group names a user belongs to."""
    resp = client.admin_list_groups_for_user(
        UserPoolId=COGNITO_USER_POOL_ID,
        Username=username,
    )
    return [g["GroupName"] for g in resp.get("Groups", [])]


def _user_to_dict(user: dict, groups: list[str] | None = None) -> dict:
    """Convert a Cognito user record to a frontend-friendly dict."""
    attrs = {a["Name"]: a["Value"] for a in user.get("Attributes", user.get("UserAttributes", []))}
    # Determine role from groups (highest privilege wins)
    role = "viewer"
    if groups:
        if "admin" in groups:
            role = "admin"
        elif "editor" in groups:
            role = "editor"
    return {
        "username": user["Username"],
        "email": attrs.get("email", ""),
        "status": user.get("UserStatus", "UNKNOWN"),
        "enabled": user.get("Enabled", True),
        "role": role,
        "created_at": user.get("UserCreateDate", "").isoformat() if hasattr(user.get("UserCreateDate", ""), "isoformat") else str(user.get("UserCreateDate", "")),
    }


# ── List users ─────────────────────────────────────────────────────────


@router.get("")
async def list_users():
    """List all users in the Cognito user pool."""
    client = _cognito_client()
    users = []
    params = {"UserPoolId": COGNITO_USER_POOL_ID, "Limit": 60}
    while True:
        resp = client.list_users(**params)
        for u in resp.get("Users", []):
            groups = _get_user_groups(client, u["Username"])
            users.append(_user_to_dict(u, groups))
        token = resp.get("PaginationToken")
        if not token:
            break
        params["PaginationToken"] = token
    return users


# ── Create user ────────────────────────────────────────────────────────


class CreateUserRequest(BaseModel):
    email: EmailStr
    role: str = "viewer"
    temporary_password: Optional[str] = None


@router.post("", status_code=201)
async def create_user(body: CreateUserRequest):
    """Create a new Cognito user and assign them to a role group."""
    if body.role not in _GROUPS:
        raise HTTPException(400, f"Invalid role: {body.role}. Must be one of: {', '.join(_GROUPS)}")

    client = _cognito_client()
    create_params = {
        "UserPoolId": COGNITO_USER_POOL_ID,
        "Username": body.email,
        "UserAttributes": [
            {"Name": "email", "Value": body.email},
            {"Name": "email_verified", "Value": "true"},
        ],
        "MessageAction": "SUPPRESS",
    }
    if body.temporary_password:
        create_params["TemporaryPassword"] = body.temporary_password

    try:
        resp = client.admin_create_user(**create_params)
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        msg = exc.response["Error"]["Message"]
        if code == "UsernameExistsException":
            raise HTTPException(409, "A user with this email already exists")
        logger.error("Cognito admin_create_user failed: %s %s", code, msg)
        raise HTTPException(500, f"Failed to create user: {msg}")

    # Add to role group
    try:
        client.admin_add_user_to_group(
            UserPoolId=COGNITO_USER_POOL_ID,
            Username=body.email,
            GroupName=body.role,
        )
    except ClientError as exc:
        logger.error("Failed to add user to group: %s", exc)

    user = resp["User"]
    groups = [body.role]
    return _user_to_dict(user, groups)


# ── Update user role ───────────────────────────────────────────────────


class UpdateUserRequest(BaseModel):
    role: str


@router.put("/{username}")
async def update_user(username: str, body: UpdateUserRequest):
    """Change a user's role (group membership)."""
    if body.role not in _GROUPS:
        raise HTTPException(400, f"Invalid role: {body.role}. Must be one of: {', '.join(_GROUPS)}")

    client = _cognito_client()

    # Verify user exists
    try:
        user = client.admin_get_user(
            UserPoolId=COGNITO_USER_POOL_ID,
            Username=username,
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "UserNotFoundException":
            raise HTTPException(404, "User not found")
        raise

    # Remove from all role groups, then add to the new one
    current_groups = _get_user_groups(client, username)
    for g in current_groups:
        if g in _GROUPS:
            client.admin_remove_user_from_group(
                UserPoolId=COGNITO_USER_POOL_ID,
                Username=username,
                GroupName=g,
            )
    client.admin_add_user_to_group(
        UserPoolId=COGNITO_USER_POOL_ID,
        Username=username,
        GroupName=body.role,
    )

    return _user_to_dict(user, [body.role])


# ── Enable / disable user ────────────────────────────────────────────


@router.post("/{username}/disable")
async def disable_user(username: str):
    """Disable a Cognito user (prevents sign-in)."""
    client = _cognito_client()
    try:
        client.admin_disable_user(
            UserPoolId=COGNITO_USER_POOL_ID,
            Username=username,
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "UserNotFoundException":
            raise HTTPException(404, "User not found")
        raise
    return {"ok": True}


@router.post("/{username}/enable")
async def enable_user(username: str):
    """Re-enable a previously disabled Cognito user."""
    client = _cognito_client()
    try:
        client.admin_enable_user(
            UserPoolId=COGNITO_USER_POOL_ID,
            Username=username,
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "UserNotFoundException":
            raise HTTPException(404, "User not found")
        raise
    return {"ok": True}


# ── Reset password ────────────────────────────────────────────────────


class ResetPasswordRequest(BaseModel):
    temporary_password: str


@router.post("/{username}/reset-password")
async def reset_password(username: str, body: ResetPasswordRequest):
    """Set a new temporary password for a user (forces change on next login)."""
    client = _cognito_client()
    try:
        client.admin_set_user_password(
            UserPoolId=COGNITO_USER_POOL_ID,
            Username=username,
            Password=body.temporary_password,
            Permanent=False,
        )
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        msg = exc.response["Error"]["Message"]
        if code == "UserNotFoundException":
            raise HTTPException(404, "User not found")
        raise HTTPException(400, msg)
    return {"ok": True}
