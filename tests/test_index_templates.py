"""Tests for the Artists' Index template API routes (/index/templates)."""

import hashlib
import json
import uuid

import pytest

from backend.app.models.ruleset_model import Ruleset


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_index_ruleset(db, *, name, is_builtin=False):
    """Insert an index_template Ruleset row directly and return it."""
    cfg = {
        "entry_style": "Index Text",
        "ra_surname_style": "RA Member Cap Surname",
        "ra_caps_style": "RA Caps",
        "cat_no_style": "Index works numbers",
        "honorifics_style": "Small caps",
        "expert_numbers_style": "Expert numbers",
        "quals_lowercase": True,
        "expert_numbers_enabled": False,
        "cat_no_separator": ",",
    }
    r = Ruleset(
        name=name,
        config=cfg,
        config_hash=hashlib.sha256(
            json.dumps(cfg, sort_keys=True).encode()
        ).hexdigest(),
        config_type="index_template",
        is_builtin=is_builtin,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def _minimal_index_template_body(**overrides):
    """Minimal valid body for POST/PUT /index/templates."""
    body = {
        "name": "Test Index Template",
        "entry_style": "Index Text",
        "ra_surname_style": "RA Member Cap Surname",
        "ra_caps_style": "RA Caps",
        "cat_no_style": "Index works numbers",
        "honorifics_style": "Small caps",
        "expert_numbers_style": "Expert numbers",
        "quals_lowercase": True,
        "expert_numbers_enabled": False,
        "cat_no_separator": ",",
    }
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# GET /index/templates
# ---------------------------------------------------------------------------


def test_list_index_templates_empty(client):
    r = client.get("/index/templates")
    assert r.status_code == 200
    assert r.json() == []


def test_list_index_templates_returns_created(client):
    client.post("/index/templates", json=_minimal_index_template_body(name="Alpha"))
    client.post("/index/templates", json=_minimal_index_template_body(name="Beta"))

    r = client.get("/index/templates")
    assert r.status_code == 200
    names = [t["name"] for t in r.json()]
    assert "Alpha" in names
    assert "Beta" in names


def test_list_index_templates_excludes_low_templates(client, db_session):
    """LoW templates (config_type='template') must not appear in index list."""
    low_cfg = {"currency_symbol": "£", "components": []}
    db_session.add(
        Ruleset(
            name="LoW Template",
            config=low_cfg,
            config_hash=hashlib.sha256(
                json.dumps(low_cfg, sort_keys=True).encode()
            ).hexdigest(),
            config_type="template",
            is_builtin=False,
        )
    )
    db_session.commit()

    r = client.get("/index/templates")
    names = [t["name"] for t in r.json()]
    assert "LoW Template" not in names


def test_list_index_templates_excludes_archived(client):
    r = client.post(
        "/index/templates",
        json=_minimal_index_template_body(name="To Delete"),
    )
    tmpl_id = r.json()["id"]
    client.delete(f"/index/templates/{tmpl_id}")

    r = client.get("/index/templates")
    names = [t["name"] for t in r.json()]
    assert "To Delete" not in names


# ---------------------------------------------------------------------------
# POST /index/templates
# ---------------------------------------------------------------------------


def test_create_index_template_returns_201(client):
    r = client.post(
        "/index/templates",
        json=_minimal_index_template_body(name="New Idx Tmpl"),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "New Idx Tmpl"
    assert "id" in body
    assert body["is_builtin"] is False
    uuid.UUID(body["id"])


# ---------------------------------------------------------------------------
# GET /index/templates/{id}
# ---------------------------------------------------------------------------


def test_get_index_template_full_config(client):
    r = client.post(
        "/index/templates",
        json=_minimal_index_template_body(name="Detail"),
    )
    tid = r.json()["id"]
    r2 = client.get(f"/index/templates/{tid}")
    assert r2.status_code == 200
    body = r2.json()
    assert body["name"] == "Detail"
    assert body["entry_style"] == "Index Text"
    assert body["ra_caps_style"] == "RA Caps"


def test_get_index_template_404_for_unknown(client):
    fake = str(uuid.uuid4())
    r = client.get(f"/index/templates/{fake}")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# PUT /index/templates/{id}
# ---------------------------------------------------------------------------


def test_update_index_template(client):
    r = client.post(
        "/index/templates",
        json=_minimal_index_template_body(name="Original"),
    )
    tid = r.json()["id"]

    r2 = client.put(
        f"/index/templates/{tid}",
        json=_minimal_index_template_body(name="Updated", ra_caps_style="NewStyle"),
    )
    assert r2.status_code == 200
    assert r2.json()["name"] == "Updated"

    r3 = client.get(f"/index/templates/{tid}")
    assert r3.json()["ra_caps_style"] == "NewStyle"


def test_update_builtin_index_template_forbidden(client, db_session):
    r = _make_index_ruleset(db_session, name="Builtin", is_builtin=True)
    resp = client.put(
        f"/index/templates/{r.id}",
        json=_minimal_index_template_body(name="Hacked"),
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# DELETE /index/templates/{id}
# ---------------------------------------------------------------------------


def test_delete_index_template(client):
    r = client.post(
        "/index/templates",
        json=_minimal_index_template_body(name="Bye"),
    )
    tid = r.json()["id"]
    r2 = client.delete(f"/index/templates/{tid}")
    assert r2.status_code == 204


def test_delete_builtin_index_template_forbidden(client, db_session):
    r = _make_index_ruleset(db_session, name="Builtin", is_builtin=True)
    resp = client.delete(f"/index/templates/{r.id}")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /index/templates/{id}/duplicate
# ---------------------------------------------------------------------------


def test_duplicate_index_template(client):
    r = client.post(
        "/index/templates",
        json=_minimal_index_template_body(name="Original"),
    )
    tid = r.json()["id"]

    r2 = client.post(f"/index/templates/{tid}/duplicate")
    assert r2.status_code == 201
    body = r2.json()
    assert body["name"] == "Copy of Original"
    assert body["id"] != tid
    assert body["is_builtin"] is False
