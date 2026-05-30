"""Tests for the Known Artists API routes."""

import uuid

from backend.app.models.known_artist_model import KnownArtist

# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


class TestKnownArtistsCRUD:
    def test_list_empty(self, client):
        resp = client.get("/known-artists")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_create_and_list(self, client):
        body = {
            "match_first_name": "Boyd",
            "match_last_name": "& Evans",
            "resolved_last_name": "Boyd & Evans",
            "resolved_is_company": True,
            "notes": "Partnership",
        }
        resp = client.post("/known-artists", json=body)
        assert resp.status_code == 201
        data = resp.json()
        assert data["match_first_name"] == "Boyd"
        assert data["match_last_name"] == "& Evans"
        assert data["resolved_last_name"] == "Boyd & Evans"
        assert data["resolved_is_company"] is True
        assert data["notes"] == "Partnership"
        assert data["id"]

        # List should contain the new entry
        resp2 = client.get("/known-artists")
        assert resp2.status_code == 200
        items = resp2.json()
        assert len(items) == 1
        assert items[0]["id"] == data["id"]

    def test_update(self, client, db_session):
        ka = KnownArtist(
            match_first_name="Boyd",
            match_last_name="& Evans",
            resolved_last_name="Boyd & Evans",
            resolved_is_company=True,
        )
        db_session.add(ka)
        db_session.commit()

        resp = client.patch(
            f"/known-artists/{ka.id}",
            json={"notes": "Updated note"},
        )
        assert resp.status_code == 200
        assert resp.json()["notes"] == "Updated note"
        # Other fields should be unchanged
        assert resp.json()["resolved_last_name"] == "Boyd & Evans"

    def test_delete(self, client, db_session):
        ka = KnownArtist(
            match_first_name="Test",
            match_last_name="Delete",
        )
        db_session.add(ka)
        db_session.commit()

        resp = client.delete(f"/known-artists/{ka.id}")
        assert resp.status_code == 204

        # Should be gone
        resp2 = client.get("/known-artists")
        assert len(resp2.json()) == 0

    def test_delete_not_found(self, client):
        fake_id = str(uuid.uuid4())
        resp = client.delete(f"/known-artists/{fake_id}")
        assert resp.status_code == 404

    def test_update_not_found(self, client):
        fake_id = str(uuid.uuid4())
        resp = client.patch(
            f"/known-artists/{fake_id}",
            json={"notes": "nope"},
        )
        assert resp.status_code == 404

    def test_seed(self, client):
        """Seeding should load entries from the JSON file."""
        resp = client.post("/known-artists/seed")
        assert resp.status_code == 200
        data = resp.json()
        assert data["added"] >= 1
        assert data["total"] >= 1

        # Second seed should skip all
        resp2 = client.post("/known-artists/seed")
        data2 = resp2.json()
        assert data2["added"] == 0
        assert data2["skipped"] == data["total"]

    def test_seed_propagates_fields_and_marks_is_seeded(self, client, db_session):
        """Endpoint inserts rows that round-trip every JSON field + carry is_seeded=True.

        The structural test in tests/test_seed_templates.py asserts the same
        guarantees against the *service function*. This test asserts they
        also hold via the API endpoint -- i.e. confirms the consolidation
        in the 2026-05-30 seed-loader-audit PR did not regress field
        propagation when the endpoint switched from its own constructor
        to delegating to the service.
        """
        import json
        from pathlib import Path

        resp = client.post("/known-artists/seed")
        assert resp.status_code == 200

        seed_file = (
            Path(__file__).resolve().parent.parent
            / "backend"
            / "seed_templates"
            / "known-artists.json"
        )
        with open(seed_file, encoding="utf-8") as fp:
            entries = json.load(fp)

        rows = db_session.query(KnownArtist).all()
        assert len(rows) == len(entries)

        rows_by_key = {(r.match_first_name, r.match_last_name, r.match_quals): r for r in rows}
        for entry in entries:
            key = (
                entry.get("match_first_name"),
                entry.get("match_last_name"),
                entry.get("match_quals"),
            )
            row = rows_by_key[key]
            for field, expected in entry.items():
                actual = getattr(row, field)
                assert actual == expected, (
                    f"endpoint did not propagate {field!r} on entry {key!r}: "
                    f"json={expected!r} db={actual!r}"
                )
            assert row.is_seeded is True, (
                f"endpoint left is_seeded={row.is_seeded!r} on entry {key!r}"
            )
