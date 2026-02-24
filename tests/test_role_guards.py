"""
tests/test_role_guards.py

Tests for the three-tier permission system (viewer / editor / admin).

Each test sends requests with the X-User-Role header set to a specific role
and asserts that the endpoint either allows or rejects the request with 403.
"""

import hashlib
import json
import uuid
from io import BytesIO

import pytest

from backend.app.api.auth import get_current_role, Role
from backend.app.models.ruleset_model import Ruleset
from backend.app.models.import_model import Import
from backend.app.models.section_model import Section
from backend.app.models.work_model import Work
from backend.app.models.index_artist_model import IndexArtist
from backend.app.models.index_cat_number_model import IndexCatNumber
from backend.app.models.known_artist_model import KnownArtist
from fastapi import Depends


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_import(db):
    """Create a minimal LoW import with one section and one work."""
    imp = Import(
        filename="test.xlsx", disk_filename="test.xlsx", product_type="list_of_works"
    )
    db.add(imp)
    db.flush()
    sec = Section(import_id=imp.id, name="A", position=1)
    db.add(sec)
    db.flush()
    work = Work(
        import_id=imp.id,
        section_id=sec.id,
        position_in_section=1,
        raw_cat_no="1",
        number=1,
        artist_name="Test",
        title="Test Work",
    )
    db.add(work)
    db.commit()
    return imp, work


def _seed_index_import(db):
    """Create a minimal index import with one artist."""
    imp = Import(
        filename="index.xlsx", disk_filename="index.xlsx", product_type="artists_index"
    )
    db.add(imp)
    db.flush()
    artist = IndexArtist(
        import_id=imp.id,
        row_number=1,
        raw_last_name="Smith",
        raw_first_name="John",
        last_name="Smith",
        first_name="John",
        sort_key="smith, john",
    )
    db.add(artist)
    db.flush()
    cn = IndexCatNumber(artist_id=artist.id, cat_no=1, source_row=1)
    db.add(cn)
    db.commit()
    return imp, artist


def _seed_template(db, config_type="template"):
    """Create a user (non-builtin) template."""
    cfg = {"currency_symbol": "£", "components": []}
    r = Ruleset(
        name="Test Template",
        config=cfg,
        config_hash=hashlib.sha256(
            json.dumps(cfg, sort_keys=True).encode()
        ).hexdigest(),
        config_type=config_type,
        is_builtin=False,
    )
    db.add(r)
    db.commit()
    return r


def _seed_known_artist(db):
    """Create a known artist entry."""
    ka = KnownArtist(
        match_first_name="Jo",
        match_last_name="Test",
        resolved_first_name="John",
        resolved_last_name="Test",
    )
    db.add(ka)
    db.commit()
    return ka


# ---------------------------------------------------------------------------
# /me endpoint (needs special fixture since /me lives in main.py, not router)
# ---------------------------------------------------------------------------


@pytest.fixture()
def me_client():
    """TestClient with just the /me endpoint (no DB needed)."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()

    @app.get("/me")
    def me(role: Role = Depends(get_current_role)):
        return {"role": role.name}

    with TestClient(app) as c:
        yield c


class TestMeEndpoint:
    def test_default_role_is_admin(self, me_client):
        r = me_client.get("/me")
        assert r.status_code == 200
        assert r.json()["role"] == "admin"

    def test_viewer_role(self, me_client):
        r = me_client.get("/me", headers={"X-User-Role": "viewer"})
        assert r.status_code == 200
        assert r.json()["role"] == "viewer"

    def test_editor_role(self, me_client):
        r = me_client.get("/me", headers={"X-User-Role": "editor"})
        assert r.status_code == 200
        assert r.json()["role"] == "editor"

    def test_invalid_role(self, me_client):
        r = me_client.get("/me", headers={"X-User-Role": "superadmin"})
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# LoW overrides – PUT/DELETE/PATCH require editor
# ---------------------------------------------------------------------------


class TestOverrideRoles:
    def test_viewer_cannot_set_override(self, client, db_session):
        imp, work = _seed_import(db_session)
        r = client.put(
            f"/imports/{imp.id}/works/{work.id}/override",
            json={"title_override": "New"},
            headers={"X-User-Role": "viewer"},
        )
        assert r.status_code == 403

    def test_editor_can_set_override(self, client, db_session):
        imp, work = _seed_import(db_session)
        r = client.put(
            f"/imports/{imp.id}/works/{work.id}/override",
            json={"title_override": "New"},
            headers={"X-User-Role": "editor"},
        )
        assert r.status_code == 200

    def test_viewer_cannot_exclude_work(self, client, db_session):
        imp, work = _seed_import(db_session)
        r = client.patch(
            f"/imports/{imp.id}/works/{work.id}/exclude?exclude=true",
            headers={"X-User-Role": "viewer"},
        )
        assert r.status_code == 403

    def test_editor_can_exclude_work(self, client, db_session):
        imp, work = _seed_import(db_session)
        r = client.patch(
            f"/imports/{imp.id}/works/{work.id}/exclude?exclude=true",
            headers={"X-User-Role": "editor"},
        )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Templates – POST/PUT=editor, DELETE=admin
# ---------------------------------------------------------------------------


class TestTemplateRoles:
    def test_viewer_can_list_templates(self, client, db_session):
        _seed_template(db_session)
        r = client.get("/templates", headers={"X-User-Role": "viewer"})
        assert r.status_code == 200

    def test_viewer_cannot_create_template(self, client):
        body = {"name": "T", "currency_symbol": "£", "components": []}
        r = client.post("/templates", json=body, headers={"X-User-Role": "viewer"})
        assert r.status_code == 403

    def test_editor_can_create_template(self, client):
        body = {"name": "T", "currency_symbol": "£", "components": []}
        r = client.post("/templates", json=body, headers={"X-User-Role": "editor"})
        assert r.status_code == 201

    def test_editor_cannot_delete_template(self, client, db_session):
        t = _seed_template(db_session)
        r = client.delete(f"/templates/{t.id}", headers={"X-User-Role": "editor"})
        assert r.status_code == 403

    def test_admin_can_delete_template(self, client, db_session):
        t = _seed_template(db_session)
        r = client.delete(f"/templates/{t.id}", headers={"X-User-Role": "admin"})
        assert r.status_code == 204


# ---------------------------------------------------------------------------
# Normalisation config – PUT=admin
# ---------------------------------------------------------------------------


class TestConfigRoles:
    def test_viewer_can_read_config(self, client):
        r = client.get("/config", headers={"X-User-Role": "viewer"})
        assert r.status_code == 200

    def test_editor_cannot_update_config(self, client):
        r = client.put(
            "/config",
            json={"honorific_tokens": ["RA"]},
            headers={"X-User-Role": "editor"},
        )
        assert r.status_code == 403

    def test_admin_can_update_config(self, client):
        r = client.put(
            "/config",
            json={"honorific_tokens": ["RA"]},
            headers={"X-User-Role": "admin"},
        )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Index artist routes – override/exclude/company=editor, delete=admin
# ---------------------------------------------------------------------------


class TestIndexRoles:
    def test_viewer_can_list_index_artists(self, client, db_session):
        imp, _ = _seed_index_import(db_session)
        r = client.get(
            f"/index/imports/{imp.id}/artists",
            headers={"X-User-Role": "viewer"},
        )
        assert r.status_code == 200

    def test_viewer_cannot_set_index_override(self, client, db_session):
        imp, artist = _seed_index_import(db_session)
        r = client.put(
            f"/index/imports/{imp.id}/artists/{artist.id}/override",
            json={"first_name_override": "Jane"},
            headers={"X-User-Role": "viewer"},
        )
        assert r.status_code == 403

    def test_editor_can_set_index_override(self, client, db_session):
        imp, artist = _seed_index_import(db_session)
        r = client.put(
            f"/index/imports/{imp.id}/artists/{artist.id}/override",
            json={"first_name_override": "Jane"},
            headers={"X-User-Role": "editor"},
        )
        assert r.status_code == 200

    def test_viewer_cannot_exclude_artist(self, client, db_session):
        imp, artist = _seed_index_import(db_session)
        r = client.patch(
            f"/index/imports/{imp.id}/artists/{artist.id}/exclude?exclude=true",
            headers={"X-User-Role": "viewer"},
        )
        assert r.status_code == 403

    def test_viewer_cannot_toggle_company(self, client, db_session):
        imp, artist = _seed_index_import(db_session)
        r = client.patch(
            f"/index/imports/{imp.id}/artists/{artist.id}/company?is_company=true",
            headers={"X-User-Role": "viewer"},
        )
        assert r.status_code == 403

    def test_editor_cannot_delete_index_import(self, client, db_session):
        imp, _ = _seed_index_import(db_session)
        r = client.delete(
            f"/index/imports/{imp.id}",
            headers={"X-User-Role": "editor"},
        )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Index templates – mirror LoW template tiers
# ---------------------------------------------------------------------------


class TestIndexTemplateRoles:
    def test_viewer_cannot_create(self, client):
        body = {"name": "T", "paragraph_separator": ""}
        r = client.post(
            "/index/templates", json=body, headers={"X-User-Role": "viewer"}
        )
        assert r.status_code == 403

    def test_editor_can_create(self, client):
        body = {"name": "T", "paragraph_separator": ""}
        r = client.post(
            "/index/templates", json=body, headers={"X-User-Role": "editor"}
        )
        assert r.status_code == 201

    def test_editor_cannot_delete(self, client, db_session):
        t = _seed_template(db_session, config_type="index_template")
        r = client.delete(
            f"/index/templates/{t.id}",
            headers={"X-User-Role": "editor"},
        )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Known artists – POST/PATCH/DELETE=editor, seed=admin
# ---------------------------------------------------------------------------


class TestKnownArtistRoles:
    def test_viewer_can_list(self, client, db_session):
        r = client.get("/known-artists", headers={"X-User-Role": "viewer"})
        assert r.status_code == 200

    def test_viewer_cannot_create(self, client):
        body = {"match_first_name": "Jo", "match_last_name": "Test"}
        r = client.post("/known-artists", json=body, headers={"X-User-Role": "viewer"})
        assert r.status_code == 403

    def test_editor_can_create(self, client):
        body = {"match_first_name": "Jo", "match_last_name": "Test"}
        r = client.post("/known-artists", json=body, headers={"X-User-Role": "editor"})
        assert r.status_code == 201

    def test_editor_can_delete(self, client, db_session):
        ka = _seed_known_artist(db_session)
        r = client.delete(
            f"/known-artists/{ka.id}",
            headers={"X-User-Role": "editor"},
        )
        assert r.status_code == 204

    def test_editor_cannot_seed(self, client):
        r = client.post("/known-artists/seed", headers={"X-User-Role": "editor"})
        assert r.status_code == 403

    def test_admin_can_seed(self, client):
        # Will get 404 if seed file doesn't exist, but should not be 403
        r = client.post("/known-artists/seed", headers={"X-User-Role": "admin"})
        assert r.status_code != 403
