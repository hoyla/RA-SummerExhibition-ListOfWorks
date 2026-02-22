"""
tests/test_routes.py

Integration tests for the /config and /templates API endpoints, plus a unit
test for resolve_export_config.  Uses an in-memory SQLite DB via the conftest
fixtures.
"""

import hashlib
import json
import uuid

import pytest

from backend.app.models.ruleset_model import Ruleset
from backend.app.services.export_renderer import resolve_export_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ruleset(db, *, name, config_type="template", is_builtin=False, slug=None):
    """Insert a Ruleset row directly and return it."""
    cfg = {"currency_symbol": "£", "components": []}
    r = Ruleset(
        name=name,
        config=cfg,
        config_hash=hashlib.sha256(
            json.dumps(cfg, sort_keys=True).encode()
        ).hexdigest(),
        config_type=config_type,
        is_builtin=is_builtin,
        slug=slug,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def _minimal_template_body(**overrides):
    """Minimal valid body for POST/PUT /templates."""
    body = {
        "name": "Test Template",
        "currency_symbol": "£",
        "section_style": "SectionTitle",
        "entry_style": "CatalogueEntry",
        "edition_prefix": "edition of",
        "edition_brackets": True,
        "cat_no_style": "CatNo",
        "artist_style": "ArtistName",
        "honorifics_style": "Honorifics",
        "honorifics_lowercase": False,
        "title_style": "WorkTitle",
        "price_style": "Price",
        "medium_style": "Medium",
        "artwork_style": "Artwork",
        "thousands_separator": ",",
        "decimal_places": 0,
        "leading_separator": "none",
        "trailing_separator": "none",
        "final_sep_from_last_component": False,
        "components": [
            {"field": "work_number", "separator_after": "tab"},
            {"field": "artist", "separator_after": "tab"},
            {"field": "title", "separator_after": "tab"},
            {"field": "edition", "separator_after": "tab"},
            {"field": "artwork", "separator_after": "tab", "enabled": False},
            {"field": "price", "separator_after": "none"},
            {"field": "medium", "separator_after": "none"},
        ],
    }
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# GET /config
# ---------------------------------------------------------------------------


def test_get_config_returns_default_honorifics_when_db_empty(client):
    r = client.get("/config")
    assert r.status_code == 200
    data = r.json()
    assert "honorific_tokens" in data
    assert "RA" in data["honorific_tokens"]


def test_put_config_then_get_returns_saved_tokens(client):
    tokens = ["RA", "HON"]
    r = client.put("/config", json={"honorific_tokens": tokens})
    assert r.status_code == 200

    r2 = client.get("/config")
    assert r2.status_code == 200
    assert r2.json()["honorific_tokens"] == tokens


def test_put_config_second_put_overwrites_first(client):
    client.put("/config", json={"honorific_tokens": ["RA"]})
    client.put("/config", json={"honorific_tokens": ["PRA", "PPRA"]})

    r = client.get("/config")
    assert r.json()["honorific_tokens"] == ["PRA", "PPRA"]


# ---------------------------------------------------------------------------
# GET /templates
# ---------------------------------------------------------------------------


def test_list_templates_empty(client):
    r = client.get("/templates")
    assert r.status_code == 200
    assert r.json() == []


def test_list_templates_returns_created_templates(client):
    client.post("/templates", json=_minimal_template_body(name="Alpha"))
    client.post("/templates", json=_minimal_template_body(name="Beta"))

    r = client.get("/templates")
    assert r.status_code == 200
    names = [t["name"] for t in r.json()]
    assert "Alpha" in names
    assert "Beta" in names


def test_list_templates_sort_order_builtins_first_then_alpha(client, db_session):
    # Insert two built-in templates directly
    _make_ruleset(db_session, name="Zebra Built-in", is_builtin=True)
    _make_ruleset(db_session, name="Apple Built-in", is_builtin=True)
    # Create a user template via the API
    client.post("/templates", json=_minimal_template_body(name="Middle User"))

    r = client.get("/templates")
    names = [t["name"] for t in r.json()]

    # All builtins before any user templates
    builtin_indices = [i for i, t in enumerate(r.json()) if t["is_builtin"]]
    user_indices = [i for i, t in enumerate(r.json()) if not t["is_builtin"]]
    assert max(builtin_indices) < min(user_indices)

    # Builtins sorted alphabetically among themselves
    builtin_names = [names[i] for i in builtin_indices]
    assert builtin_names == sorted(builtin_names)


def test_list_templates_excludes_archived(client, db_session):
    r = client.post("/templates", json=_minimal_template_body(name="To Delete"))
    tmpl_id = r.json()["id"]
    client.delete(f"/templates/{tmpl_id}")

    r = client.get("/templates")
    names = [t["name"] for t in r.json()]
    assert "To Delete" not in names


# ---------------------------------------------------------------------------
# POST /templates
# ---------------------------------------------------------------------------


def test_create_template_returns_201_with_id(client):
    r = client.post("/templates", json=_minimal_template_body(name="New Tmpl"))
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "New Tmpl"
    assert "id" in body
    assert body["is_builtin"] is False
    # id should be a valid UUID
    uuid.UUID(body["id"])


# ---------------------------------------------------------------------------
# GET /templates/{id}
# ---------------------------------------------------------------------------


def test_get_template_returns_full_config(client):
    r = client.post(
        "/templates",
        json=_minimal_template_body(name="Detailed", currency_symbol="$"),
    )
    tmpl_id = r.json()["id"]

    r2 = client.get(f"/templates/{tmpl_id}")
    assert r2.status_code == 200
    data = r2.json()
    assert data["name"] == "Detailed"
    assert data["currency_symbol"] == "$"
    assert "components" in data


def test_get_template_404_for_unknown_id(client):
    r = client.get(f"/templates/{uuid.uuid4()}")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# PUT /templates/{id}
# ---------------------------------------------------------------------------


def test_update_template_changes_name_and_config(client):
    r = client.post("/templates", json=_minimal_template_body(name="Old Name"))
    tmpl_id = r.json()["id"]

    r2 = client.put(
        f"/templates/{tmpl_id}",
        json=_minimal_template_body(name="New Name", currency_symbol="€"),
    )
    assert r2.status_code == 200
    assert r2.json()["name"] == "New Name"

    r3 = client.get(f"/templates/{tmpl_id}")
    assert r3.json()["currency_symbol"] == "€"


def test_update_builtin_returns_403(client, db_session):
    builtin = _make_ruleset(db_session, name="Read Only", is_builtin=True)

    r = client.put(
        f"/templates/{builtin.id}",
        json=_minimal_template_body(name="Hacked"),
    )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# DELETE /templates/{id}
# ---------------------------------------------------------------------------


def test_delete_template_returns_204(client):
    r = client.post("/templates", json=_minimal_template_body(name="Tmp"))
    tmpl_id = r.json()["id"]

    r2 = client.delete(f"/templates/{tmpl_id}")
    assert r2.status_code == 204


def test_delete_template_hides_from_list(client):
    r = client.post("/templates", json=_minimal_template_body(name="Gone"))
    tmpl_id = r.json()["id"]
    client.delete(f"/templates/{tmpl_id}")

    r2 = client.get("/templates")
    assert all(t["id"] != tmpl_id for t in r2.json())


def test_delete_builtin_returns_403(client, db_session):
    builtin = _make_ruleset(db_session, name="Protected", is_builtin=True)

    r = client.delete(f"/templates/{builtin.id}")
    assert r.status_code == 403


def test_delete_nonexistent_returns_404(client):
    r = client.delete(f"/templates/{uuid.uuid4()}")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /templates/{id}/duplicate
# ---------------------------------------------------------------------------


def test_duplicate_creates_copy_with_new_id(client):
    r = client.post("/templates", json=_minimal_template_body(name="Original"))
    orig_id = r.json()["id"]

    r2 = client.post(f"/templates/{orig_id}/duplicate")
    assert r2.status_code == 201
    copy = r2.json()
    assert copy["id"] != orig_id
    assert copy["name"] == "Copy of Original"
    assert copy["is_builtin"] is False


def test_duplicate_builtin_creates_editable_copy(client, db_session):
    builtin = _make_ruleset(db_session, name="Seed", is_builtin=True)

    r = client.post(f"/templates/{builtin.id}/duplicate")
    assert r.status_code == 201
    copy = r.json()
    assert copy["name"] == "Copy of Seed"
    assert copy["is_builtin"] is False


def test_duplicate_nonexistent_returns_404(client):
    r = client.post(f"/templates/{uuid.uuid4()}/duplicate")
    assert r.status_code == 404


def test_duplicate_copy_is_independent(client):
    """Editing the copy must not affect the original."""
    r = client.post("/templates", json=_minimal_template_body(name="Parent"))
    parent_id = r.json()["id"]

    r2 = client.post(f"/templates/{parent_id}/duplicate")
    copy_id = r2.json()["id"]

    client.put(
        f"/templates/{copy_id}",
        json=_minimal_template_body(name="Copy Modified", currency_symbol="€"),
    )

    r3 = client.get(f"/templates/{parent_id}")
    assert r3.json()["name"] == "Parent"
    assert r3.json()["currency_symbol"] == "£"


# ---------------------------------------------------------------------------
# resolve_export_config (unit tests – bypass HTTP)
# ---------------------------------------------------------------------------


def test_resolve_export_config_returns_none_when_no_id(db_session):
    result = resolve_export_config(db_session, ruleset_id=None)
    assert result is None


def test_resolve_export_config_returns_ruleset_for_valid_id(db_session):
    tmpl = _make_ruleset(db_session, name="Export Config", config_type="template")
    result = resolve_export_config(db_session, ruleset_id=tmpl.id)
    assert result is not None
    assert result.id == tmpl.id


def test_resolve_export_config_ignores_normalisation_rows(db_session):
    """A normalisation row must never be used as a template."""
    norm = _make_ruleset(
        db_session, name="global_normalisation", config_type="normalisation"
    )
    result = resolve_export_config(db_session, ruleset_id=norm.id)
    assert result is None


def test_resolve_export_config_returns_none_for_unknown_id(db_session):
    result = resolve_export_config(db_session, ruleset_id=uuid.uuid4())
    assert result is None
