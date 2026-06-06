"""Tests for the editable free-text "Import description" field.

Covers both product types (list-of-works and Artists' Index): set/clear,
whitespace normalisation, the 256-character cap, editor gating, and 404s
(including cross-product-type rejection). The description is shown read-only
in the import lists and edited only on the detail pages.
"""

from backend.app.models.import_model import Import

VIEWER = {"X-User-Role": "viewer"}


def _make_import(db, product_type: str) -> str:
    imp = Import(filename=f"{product_type}.xlsx", product_type=product_type)
    db.add(imp)
    db.commit()
    db.refresh(imp)
    return str(imp.id)


class TestLowImportDescription:
    def test_default_is_none(self, client, db_session):
        iid = _make_import(db_session, "list_of_works")
        row = next(r for r in client.get("/imports").json() if r["id"] == iid)
        assert row["description"] is None

    def test_set_then_appears_in_list(self, client, db_session):
        iid = _make_import(db_session, "list_of_works")

        r = client.patch(f"/imports/{iid}", json={"description": "Curator's working copy"})
        assert r.status_code == 200
        assert r.json() == {"id": iid, "description": "Curator's working copy"}

        row = next(r for r in client.get("/imports").json() if r["id"] == iid)
        assert row["description"] == "Curator's working copy"

    def test_whitespace_trimmed(self, client, db_session):
        iid = _make_import(db_session, "list_of_works")
        r = client.patch(f"/imports/{iid}", json={"description": "  padded  "})
        assert r.json()["description"] == "padded"

    def test_blank_clears_to_null(self, client, db_session):
        iid = _make_import(db_session, "list_of_works")
        client.patch(f"/imports/{iid}", json={"description": "something"})
        r = client.patch(f"/imports/{iid}", json={"description": "   "})
        assert r.status_code == 200
        assert r.json()["description"] is None

    def test_max_length_256_ok_257_rejected(self, client, db_session):
        iid = _make_import(db_session, "list_of_works")
        assert client.patch(f"/imports/{iid}", json={"description": "x" * 256}).status_code == 200
        assert client.patch(f"/imports/{iid}", json={"description": "x" * 257}).status_code == 422

    def test_unknown_id_404(self, client):
        r = client.patch(
            "/imports/00000000-0000-0000-0000-000000000000",
            json={"description": "x"},
        )
        assert r.status_code == 404

    def test_index_import_not_reachable_via_low_route(self, client, db_session):
        idx = _make_import(db_session, "artists_index")
        r = client.patch(f"/imports/{idx}", json={"description": "x"})
        assert r.status_code == 404

    def test_requires_editor(self, client, db_session):
        iid = _make_import(db_session, "list_of_works")
        r = client.patch(f"/imports/{iid}", json={"description": "x"}, headers=VIEWER)
        assert r.status_code == 403


class TestIndexImportDescription:
    def test_default_is_none(self, client, db_session):
        iid = _make_import(db_session, "artists_index")
        row = next(r for r in client.get("/index/imports").json() if r["id"] == iid)
        assert row["description"] is None

    def test_set_then_appears_in_list(self, client, db_session):
        iid = _make_import(db_session, "artists_index")

        r = client.patch(f"/index/imports/{iid}", json={"description": "Final index pass"})
        assert r.status_code == 200
        assert r.json() == {"id": iid, "description": "Final index pass"}

        row = next(r for r in client.get("/index/imports").json() if r["id"] == iid)
        assert row["description"] == "Final index pass"

    def test_blank_clears_to_null(self, client, db_session):
        iid = _make_import(db_session, "artists_index")
        client.patch(f"/index/imports/{iid}", json={"description": "something"})
        r = client.patch(f"/index/imports/{iid}", json={"description": ""})
        assert r.json()["description"] is None

    def test_max_length_257_rejected(self, client, db_session):
        iid = _make_import(db_session, "artists_index")
        assert (
            client.patch(f"/index/imports/{iid}", json={"description": "x" * 257}).status_code
            == 422
        )

    def test_unknown_id_404(self, client):
        r = client.patch(
            "/index/imports/00000000-0000-0000-0000-000000000000",
            json={"description": "x"},
        )
        assert r.status_code == 404

    def test_low_import_not_reachable_via_index_route(self, client, db_session):
        low = _make_import(db_session, "list_of_works")
        r = client.patch(f"/index/imports/{low}", json={"description": "x"})
        assert r.status_code == 404

    def test_requires_editor(self, client, db_session):
        iid = _make_import(db_session, "artists_index")
        r = client.patch(f"/index/imports/{iid}", json={"description": "x"}, headers=VIEWER)
        assert r.status_code == 403
