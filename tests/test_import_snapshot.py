"""Tests for pre-reimport import snapshots (services/import_snapshot.py).

Foundation layer for the Update-Import before/after diff + undo: every real
re-import captures an append-only snapshot of the full prior mutable state
(sections -> works with raw + normalised columns -> override + warnings).
"""

import io
import uuid as _uuid

import pytest
from openpyxl import Workbook

from backend.app.models.import_snapshot_model import ImportSnapshot

# Re-import uses raise_server_exceptions=False so we can assert on status codes.
client = pytest.fixture(name="client")(lambda client_lenient: client_lenient)

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ALL_HEADERS = ["Cat No", "Gallery", "Title", "Artist", "Price", "Edition", "Artwork", "Medium"]
DEFAULT_ROWS = [
    [1, "Gallery A", "Sunset", "Jane Doe", "500", None, None, "Oil"],
    [2, "Gallery A", "Dawn", "John Smith RA", "1000", None, None, "Acrylic"],
]


def _make_xlsx(rows):
    wb = Workbook()
    ws = wb.active
    ws.append(ALL_HEADERS)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _upload(client, rows, filename="orig.xlsx"):
    r = client.post("/import", files={"file": (filename, _make_xlsx(rows), XLSX_MIME)})
    assert r.status_code == 200, r.text
    return r.json()["import_id"]


def _reimport(client, import_id, rows, filename="updated.xlsx", query=""):
    return client.put(
        f"/imports/{import_id}/reimport{query}",
        files={"file": (filename, _make_xlsx(rows), XLSX_MIME)},
    )


def _snapshots(db_session, import_id):
    return (
        db_session.query(ImportSnapshot)
        .filter(ImportSnapshot.import_id == _uuid.UUID(import_id))
        .order_by(ImportSnapshot.created_at)
        .all()
    )


def _all_works(state):
    return [w for s in state["sections"] for w in s["works"]]


class TestSnapshotCapture:
    def test_reimport_creates_snapshot_of_prior_state(self, client, db_session):
        import_id = _upload(client, DEFAULT_ROWS)
        assert _snapshots(db_session, import_id) == []  # nothing before a re-import

        r = _reimport(client, import_id, DEFAULT_ROWS)
        assert r.status_code == 200

        snaps = _snapshots(db_session, import_id)
        assert len(snaps) == 1
        # The state captures the PRE-reimport works, not the new file.
        titles = [w["raw_title"] for w in _all_works(snaps[0].state)]
        assert sorted(titles) == ["Dawn", "Sunset"]
        assert snaps[0].kind == "pre_reimport"

    def test_dry_run_creates_no_snapshot(self, client, db_session):
        import_id = _upload(client, DEFAULT_ROWS)
        r = _reimport(client, import_id, DEFAULT_ROWS, query="?dry_run=true")
        assert r.status_code == 200
        assert _snapshots(db_session, import_id) == []

    def test_snapshots_are_append_only(self, client, db_session):
        import_id = _upload(client, DEFAULT_ROWS)
        _reimport(client, import_id, DEFAULT_ROWS)
        _reimport(client, import_id, DEFAULT_ROWS)
        assert len(_snapshots(db_session, import_id)) == 2

    def test_note_records_incoming_filename(self, client, db_session):
        import_id = _upload(client, DEFAULT_ROWS)
        _reimport(client, import_id, DEFAULT_ROWS, filename="march-update.xlsx")
        assert _snapshots(db_session, import_id)[0].note == "march-update.xlsx"

    def test_failed_reimport_leaves_no_snapshot(self, client, db_session):
        """A snapshot must not survive a re-import that rolls back."""
        import_id = _upload(client, DEFAULT_ROWS)
        # Corrupt upload → 400, transaction rolled back.
        r = client.put(
            f"/imports/{import_id}/reimport",
            files={"file": ("bad.xlsx", io.BytesIO(b"not excel"), XLSX_MIME)},
        )
        assert r.status_code == 400
        assert _snapshots(db_session, import_id) == []


class TestSnapshotContents:
    def test_snapshot_captures_override_with_all_columns(self, client, db_session):
        import_id = _upload(client, DEFAULT_ROWS)
        sections = client.get(f"/imports/{import_id}/sections").json()
        work2 = next(w for s in sections for w in s["works"] if w["raw_cat_no"] == "2")
        client.put(
            f"/imports/{import_id}/works/{work2['id']}/override",
            json={"title_override": "Custom Dawn", "title_cased_override": "Custom Dawn TC"},
        )

        _reimport(client, import_id, DEFAULT_ROWS)

        snap = _snapshots(db_session, import_id)[0]
        snap_work2 = next(w for w in _all_works(snap.state) if w["raw_cat_no"] == "2")
        ovr = snap_work2["override"]
        assert ovr is not None
        assert ovr["title_override"] == "Custom Dawn"
        assert ovr["title_cased_override"] == "Custom Dawn TC"
        # Full-column serialisation: every WorkOverride column is present even
        # when unset, so a newly-added override field can't fall out silently.
        assert "artwork_override" in ovr
        assert "notes" in ovr

    def test_snapshot_captures_raw_and_normalised_layers(self, client, db_session):
        import_id = _upload(client, DEFAULT_ROWS)
        _reimport(client, import_id, DEFAULT_ROWS)
        snap = _snapshots(db_session, import_id)[0]
        work1 = next(w for w in _all_works(snap.state) if w["raw_cat_no"] == "1")
        assert work1["override"] is None
        assert work1["raw_artist"] == "Jane Doe"  # raw layer
        assert work1["title"] == "Sunset"  # normalised layer

    def test_snapshot_captures_section_structure(self, client, db_session):
        rows = [
            [1, "Gallery A", "Sunset", "Jane Doe", "500", None, None, "Oil"],
            [2, "Gallery B", "Noon", "Alice", "NFS", None, None, None],
        ]
        import_id = _upload(client, rows)
        _reimport(client, import_id, rows)
        snap = _snapshots(db_session, import_id)[0]
        names = {s["name"] for s in snap.state["sections"]}
        assert names == {"Gallery A", "Gallery B"}
