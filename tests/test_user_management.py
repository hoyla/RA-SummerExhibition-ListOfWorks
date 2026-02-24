"""
Tests for user management routes (backend/app/api/users.py).

All Cognito interactions are mocked via ``unittest.mock.patch``.
"""

import datetime
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from backend.app.api.auth import require_role, Role
from backend.app.api import users as users_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_POOL_ID = "eu-north-1_FakePool"


def _make_cognito_user(username, email, status="CONFIRMED", enabled=True):
    """Build a Cognito-style user dict."""
    return {
        "Username": username,
        "Attributes": [
            {"Name": "email", "Value": email},
        ],
        "UserStatus": status,
        "Enabled": enabled,
        "UserCreateDate": datetime.datetime(2026, 2, 24, 12, 0, 0),
    }


def _client_error(code, message="error"):
    """Build a botocore ClientError for testing."""
    return ClientError(
        {"Error": {"Code": code, "Message": message}},
        "operation_name",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_cognito():
    """Yield a (client, TestClient) pair with mocked Cognito."""
    mock_client = MagicMock()

    app = FastAPI()

    # Override the admin-only guard so we can test routes directly
    async def _noop():
        pass

    app.include_router(
        users_module.router,
        dependencies=[Depends(_noop)],  # bypass admin check
    )

    # Patch _cognito_client to return our mock, and COGNITO_USER_POOL_ID
    with (
        patch.object(users_module, "_cognito_client", return_value=mock_client),
        patch.object(users_module, "COGNITO_USER_POOL_ID", _POOL_ID),
        TestClient(app, raise_server_exceptions=False) as tc,
    ):
        yield mock_client, tc


@pytest.fixture()
def role_client():
    """TestClient that uses the *real* admin guard (no Cognito auth)."""
    from backend.app.api.import_routes import router, get_db

    app = FastAPI()
    app.include_router(router)

    # Provide a dummy DB — user routes don't use it, but other sub-routers
    # registered on the same aggregation router may need the dependency.
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from backend.app.db import Base

    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=eng)
    _Session = sessionmaker(bind=eng)

    def _override():
        s = _Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ===================================================================
# LIST USERS
# ===================================================================


class TestListUsers:
    def test_returns_empty_list(self, mock_cognito):
        client_mock, tc = mock_cognito
        client_mock.list_users.return_value = {"Users": []}
        r = tc.get("/users")
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_users_with_groups(self, mock_cognito):
        client_mock, tc = mock_cognito
        user = _make_cognito_user("abc-123", "alice@example.com")
        client_mock.list_users.return_value = {"Users": [user]}
        client_mock.admin_list_groups_for_user.return_value = {
            "Groups": [{"GroupName": "editor"}]
        }

        r = tc.get("/users")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["email"] == "alice@example.com"
        assert data[0]["role"] == "editor"

    def test_admin_group_wins_over_editor(self, mock_cognito):
        client_mock, tc = mock_cognito
        user = _make_cognito_user("abc-123", "boss@example.com")
        client_mock.list_users.return_value = {"Users": [user]}
        client_mock.admin_list_groups_for_user.return_value = {
            "Groups": [{"GroupName": "editor"}, {"GroupName": "admin"}]
        }

        r = tc.get("/users")
        assert r.json()[0]["role"] == "admin"

    def test_no_groups_defaults_to_viewer(self, mock_cognito):
        client_mock, tc = mock_cognito
        user = _make_cognito_user("abc-123", "nobody@example.com")
        client_mock.list_users.return_value = {"Users": [user]}
        client_mock.admin_list_groups_for_user.return_value = {"Groups": []}

        r = tc.get("/users")
        assert r.json()[0]["role"] == "viewer"

    def test_pagination(self, mock_cognito):
        """When Cognito returns a PaginationToken, a second page is fetched."""
        client_mock, tc = mock_cognito
        u1 = _make_cognito_user("u1", "a@a.com")
        u2 = _make_cognito_user("u2", "b@b.com")
        client_mock.list_users.side_effect = [
            {"Users": [u1], "PaginationToken": "tok"},
            {"Users": [u2]},
        ]
        client_mock.admin_list_groups_for_user.return_value = {"Groups": []}

        r = tc.get("/users")
        assert r.status_code == 200
        assert len(r.json()) == 2


# ===================================================================
# CREATE USER
# ===================================================================


class TestCreateUser:
    def test_create_basic_user(self, mock_cognito):
        client_mock, tc = mock_cognito
        client_mock.admin_create_user.return_value = {
            "User": _make_cognito_user(
                "abc-123", "new@example.com", status="FORCE_CHANGE_PASSWORD"
            )
        }
        client_mock.admin_add_user_to_group.return_value = {}

        r = tc.post(
            "/users",
            json={
                "email": "new@example.com",
                "role": "editor",
                "temporary_password": "TempPass1234",
            },
        )
        assert r.status_code == 201
        assert r.json()["email"] == "new@example.com"
        assert r.json()["role"] == "editor"
        client_mock.admin_create_user.assert_called_once()
        client_mock.admin_add_user_to_group.assert_called_once()

    def test_create_user_defaults_to_viewer(self, mock_cognito):
        client_mock, tc = mock_cognito
        client_mock.admin_create_user.return_value = {
            "User": _make_cognito_user("abc-123", "v@example.com")
        }
        client_mock.admin_add_user_to_group.return_value = {}

        r = tc.post("/users", json={"email": "v@example.com"})
        assert r.status_code == 201
        assert r.json()["role"] == "viewer"

    def test_invalid_role_rejected(self, mock_cognito):
        _, tc = mock_cognito
        r = tc.post("/users", json={"email": "x@example.com", "role": "superadmin"})
        assert r.status_code == 400
        assert "Invalid role" in r.json()["detail"]

    def test_invalid_email_rejected(self, mock_cognito):
        _, tc = mock_cognito
        r = tc.post("/users", json={"email": "not-an-email", "role": "viewer"})
        assert r.status_code == 422  # Pydantic validation

    def test_duplicate_user_returns_409(self, mock_cognito):
        client_mock, tc = mock_cognito
        client_mock.admin_create_user.side_effect = _client_error(
            "UsernameExistsException"
        )

        r = tc.post("/users", json={"email": "dup@example.com", "role": "viewer"})
        assert r.status_code == 409

    def test_cognito_error_returns_500(self, mock_cognito):
        client_mock, tc = mock_cognito
        client_mock.admin_create_user.side_effect = _client_error(
            "InternalErrorException", "Something broke"
        )

        r = tc.post("/users", json={"email": "err@example.com"})
        assert r.status_code == 500


# ===================================================================
# UPDATE USER ROLE
# ===================================================================


class TestUpdateUserRole:
    def test_change_role(self, mock_cognito):
        client_mock, tc = mock_cognito
        client_mock.admin_get_user.return_value = _make_cognito_user("u1", "u@e.com")
        client_mock.admin_list_groups_for_user.return_value = {
            "Groups": [{"GroupName": "viewer"}]
        }
        client_mock.admin_remove_user_from_group.return_value = {}
        client_mock.admin_add_user_to_group.return_value = {}

        r = tc.put("/users/u1", json={"role": "admin"})
        assert r.status_code == 200
        assert r.json()["role"] == "admin"
        client_mock.admin_remove_user_from_group.assert_called_once()
        client_mock.admin_add_user_to_group.assert_called_once()

    def test_invalid_role(self, mock_cognito):
        _, tc = mock_cognito
        r = tc.put("/users/u1", json={"role": "boss"})
        assert r.status_code == 400

    def test_user_not_found(self, mock_cognito):
        client_mock, tc = mock_cognito
        client_mock.admin_get_user.side_effect = _client_error("UserNotFoundException")

        r = tc.put("/users/ghost", json={"role": "admin"})
        assert r.status_code == 404


# ===================================================================
# ENABLE / DISABLE
# ===================================================================


class TestEnableDisable:
    def test_disable_user(self, mock_cognito):
        client_mock, tc = mock_cognito
        client_mock.admin_disable_user.return_value = {}

        r = tc.post("/users/u1/disable")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_enable_user(self, mock_cognito):
        client_mock, tc = mock_cognito
        client_mock.admin_enable_user.return_value = {}

        r = tc.post("/users/u1/enable")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_disable_not_found(self, mock_cognito):
        client_mock, tc = mock_cognito
        client_mock.admin_disable_user.side_effect = _client_error(
            "UserNotFoundException"
        )

        r = tc.post("/users/ghost/disable")
        assert r.status_code == 404

    def test_enable_not_found(self, mock_cognito):
        client_mock, tc = mock_cognito
        client_mock.admin_enable_user.side_effect = _client_error(
            "UserNotFoundException"
        )

        r = tc.post("/users/ghost/enable")
        assert r.status_code == 404


# ===================================================================
# RESET PASSWORD
# ===================================================================


class TestResetPassword:
    def test_reset_password(self, mock_cognito):
        client_mock, tc = mock_cognito
        client_mock.admin_set_user_password.return_value = {}

        r = tc.post(
            "/users/u1/reset-password", json={"temporary_password": "NewPass12345"}
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True
        call_kwargs = client_mock.admin_set_user_password.call_args.kwargs
        assert call_kwargs["Permanent"] is False

    def test_reset_password_not_found(self, mock_cognito):
        client_mock, tc = mock_cognito
        client_mock.admin_set_user_password.side_effect = _client_error(
            "UserNotFoundException"
        )

        r = tc.post("/users/ghost/reset-password", json={"temporary_password": "X"})
        assert r.status_code == 404

    def test_reset_password_invalid(self, mock_cognito):
        client_mock, tc = mock_cognito
        client_mock.admin_set_user_password.side_effect = _client_error(
            "InvalidPasswordException", "Password too short"
        )

        r = tc.post("/users/u1/reset-password", json={"temporary_password": "X"})
        assert r.status_code == 400

    def test_missing_password_body(self, mock_cognito):
        _, tc = mock_cognito
        r = tc.post("/users/u1/reset-password", json={})
        assert r.status_code == 422


# ===================================================================
# COGNITO NOT CONFIGURED (501)
# ===================================================================


class TestCognitoNotConfigured:
    def test_returns_501_when_cognito_disabled(self):
        """When COGNITO_USER_POOL_ID is empty, all routes return 501."""
        app = FastAPI()

        # Bypass admin guard
        async def _noop():
            pass

        app.include_router(
            users_module.router,
            dependencies=[Depends(_noop)],
        )

        with (
            patch.object(users_module, "COGNITO_USER_POOL_ID", ""),
            TestClient(app, raise_server_exceptions=False) as tc,
        ):
            r = tc.get("/users")
            assert r.status_code == 501
            assert "Cognito" in r.json()["detail"]


# ===================================================================
# ROLE GUARDS (using real require_role)
# ===================================================================


class TestUserRouteRoleGuards:
    """Verify that /users routes require admin role."""

    def test_viewer_cannot_list_users(self, role_client):
        r = role_client.get("/users", headers={"X-User-Role": "viewer"})
        assert r.status_code == 403

    def test_editor_cannot_list_users(self, role_client):
        r = role_client.get("/users", headers={"X-User-Role": "editor"})
        assert r.status_code == 403

    def test_admin_can_access_users(self, role_client):
        """Admin can reach the route (will get 501 since Cognito isn't configured)."""
        r = role_client.get("/users", headers={"X-User-Role": "admin"})
        # 501 = reached the handler but Cognito is disabled; not 403
        assert r.status_code == 501

    def test_viewer_cannot_create_user(self, role_client):
        r = role_client.post(
            "/users",
            json={"email": "x@example.com"},
            headers={"X-User-Role": "viewer"},
        )
        assert r.status_code == 403

    def test_editor_cannot_create_user(self, role_client):
        r = role_client.post(
            "/users",
            json={"email": "x@example.com"},
            headers={"X-User-Role": "editor"},
        )
        assert r.status_code == 403

    def test_viewer_cannot_disable_user(self, role_client):
        r = role_client.post(
            "/users/someone/disable",
            headers={"X-User-Role": "viewer"},
        )
        assert r.status_code == 403

    def test_viewer_cannot_reset_password(self, role_client):
        r = role_client.post(
            "/users/someone/reset-password",
            json={"temporary_password": "X"},
            headers={"X-User-Role": "viewer"},
        )
        assert r.status_code == 403
