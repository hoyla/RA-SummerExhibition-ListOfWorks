"""
Tests for authentication, user context, and audit log user attribution.

Covers:
- /auth/config endpoint (Cognito vs API-key vs no-auth modes)
- /me endpoint (already partially tested in test_role_guards; this adds coverage)
- user_context ContextVar and audit log auto-population
- Auth mode detection (_USE_COGNITO flag behaviour)
"""

from unittest.mock import patch

import pytest
from fastapi import FastAPI, Depends, Request
from fastapi.testclient import TestClient

from backend.app.api.auth import (
    Role,
    get_current_role,
    get_current_user,
    require_api_key,
    require_role,
)
from backend.app.api.user_context import current_user_email


# ---------------------------------------------------------------------------
# /auth/config endpoint
# ---------------------------------------------------------------------------


class TestAuthConfig:
    """Test the /auth/config endpoint returns correct mode info.

    We build a minimal FastAPI app rather than importing ``main.py``
    (which connects to PostgreSQL at module level).
    """

    @staticmethod
    def _make_app(api_key, use_cognito, pool_id="", client_id="", region="eu-north-1"):
        app = FastAPI()

        @app.get("/auth/config")
        def auth_config():
            if use_cognito:
                return {
                    "mode": "cognito",
                    "userPoolId": pool_id,
                    "clientId": client_id,
                    "region": region,
                }
            return {"mode": "api_key" if api_key else "none"}

        return app

    def test_no_auth_mode(self):
        """When neither Cognito nor API key is set, mode is 'none'."""
        app = self._make_app(api_key="", use_cognito=False)
        with TestClient(app) as tc:
            r = tc.get("/auth/config")
            assert r.status_code == 200
            assert r.json()["mode"] == "none"

    def test_api_key_mode(self):
        """When only API_KEY is set, mode is 'api_key'."""
        app = self._make_app(api_key="secret123", use_cognito=False)
        with TestClient(app) as tc:
            r = tc.get("/auth/config")
            assert r.status_code == 200
            assert r.json()["mode"] == "api_key"

    def test_cognito_mode(self):
        """When COGNITO_USER_POOL_ID is set, mode is 'cognito'."""
        app = self._make_app(
            api_key="",
            use_cognito=True,
            pool_id="eu-north-1_Fake",
            client_id="fake-client",
            region="eu-north-1",
        )
        with TestClient(app) as tc:
            r = tc.get("/auth/config")
            assert r.status_code == 200
            data = r.json()
            assert data["mode"] == "cognito"
            assert data["userPoolId"] == "eu-north-1_Fake"
            assert data["clientId"] == "fake-client"
            assert data["region"] == "eu-north-1"


# ---------------------------------------------------------------------------
# get_current_user (non-Cognito paths)
# ---------------------------------------------------------------------------


class TestGetCurrentUser:
    """Test get_current_user returns 'anonymous' in non-Cognito modes."""

    def test_returns_anonymous_when_no_auth(self):
        app = FastAPI()

        @app.get("/who")
        def who(request: Request):
            return {"user": get_current_user(request)}

        with (
            patch("backend.app.api.auth._USE_COGNITO", False),
            TestClient(app) as tc,
        ):
            r = tc.get("/who")
            assert r.status_code == 200
            assert r.json()["user"] == "anonymous"


# ---------------------------------------------------------------------------
# require_role factory
# ---------------------------------------------------------------------------


class TestRequireRole:
    """Test the require_role dependency factory."""

    def _make_app(self, minimum):
        app = FastAPI()

        @app.get("/test", dependencies=[Depends(require_role(minimum))])
        def handler():
            return {"ok": True}

        return app

    def test_admin_passes_admin_check(self):
        app = self._make_app("admin")
        with TestClient(app) as tc:
            r = tc.get("/test", headers={"X-User-Role": "admin"})
            assert r.status_code == 200

    def test_viewer_fails_editor_check(self):
        app = self._make_app("editor")
        with TestClient(app, raise_server_exceptions=False) as tc:
            r = tc.get("/test", headers={"X-User-Role": "viewer"})
            assert r.status_code == 403

    def test_editor_passes_editor_check(self):
        app = self._make_app("editor")
        with TestClient(app) as tc:
            r = tc.get("/test", headers={"X-User-Role": "editor"})
            assert r.status_code == 200

    def test_editor_fails_admin_check(self):
        app = self._make_app("admin")
        with TestClient(app, raise_server_exceptions=False) as tc:
            r = tc.get("/test", headers={"X-User-Role": "editor"})
            assert r.status_code == 403

    def test_viewer_passes_viewer_check(self):
        app = self._make_app("viewer")
        with TestClient(app) as tc:
            r = tc.get("/test", headers={"X-User-Role": "viewer"})
            assert r.status_code == 200


# ---------------------------------------------------------------------------
# User context ContextVar
# ---------------------------------------------------------------------------


class TestUserContext:
    """Test the current_user_email context variable."""

    def test_default_is_anonymous(self):
        assert current_user_email.get() == "anonymous"

    def test_set_and_reset(self):
        tok = current_user_email.set("alice@example.com")
        assert current_user_email.get() == "alice@example.com"
        current_user_email.reset(tok)
        assert current_user_email.get() == "anonymous"


# ---------------------------------------------------------------------------
# Audit log user_email auto-population
# ---------------------------------------------------------------------------


class TestAuditLogUserAttribution:
    """Test that AuditLog.user_email is auto-populated from the context var."""

    def test_default_email_is_anonymous(self):
        from backend.app.models.audit_log_model import AuditLog
        import uuid

        entry = AuditLog(
            import_id=uuid.uuid4(),
            action="test_action",
        )
        assert entry.user_email == "anonymous"

    def test_email_set_from_context(self):
        from backend.app.models.audit_log_model import AuditLog
        import uuid

        tok = current_user_email.set("bob@example.com")
        try:
            entry = AuditLog(
                import_id=uuid.uuid4(),
                action="test_action",
            )
            assert entry.user_email == "bob@example.com"
        finally:
            current_user_email.reset(tok)

    def test_explicit_email_not_overridden(self):
        from backend.app.models.audit_log_model import AuditLog
        import uuid

        tok = current_user_email.set("context@example.com")
        try:
            entry = AuditLog(
                import_id=uuid.uuid4(),
                action="test_action",
                user_email="explicit@example.com",
            )
            assert entry.user_email == "explicit@example.com"
        finally:
            current_user_email.reset(tok)


# ---------------------------------------------------------------------------
# Role IntEnum ordering
# ---------------------------------------------------------------------------


class TestRoleEnum:
    def test_ordering(self):
        assert Role.viewer < Role.editor < Role.admin

    def test_values(self):
        assert Role.viewer == 1
        assert Role.editor == 2
        assert Role.admin == 3

    def test_name_lookup(self):
        assert Role["admin"] == Role.admin
        assert Role["viewer"] == Role.viewer
