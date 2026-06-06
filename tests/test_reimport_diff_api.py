"""Tests for the read-only reimport-diff / snapshot API (api/low_snapshots.py).

GET /imports/{id}/reimport-diff           — latest snapshot vs current
GET /imports/{id}/snapshots               — list snapshots
GET /imports/{id}/snapshots/{sid}/diff    — a specific snapshot vs current
"""

import io
import uuid as _uuid

import pytest
from openpyxl import Workbook

client = pytest.fixture(name="client")(lambda client_lenient: client_lenient)

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
HEADERS = ["Cat No", "Gallery", "Title", "Artist", "Price", "Edition", "Artwork", "Medium"]
ROWS = [
    [1, "Gallery A", "Sunset", "Jane Doe", "500", None, None, "Oil"],
    [2, "Gallery A", "Dawn", "John Smith RA", "1000", None, None, "Acrylic"],
]


def _xlsx(rows):
    wb = Workbook()
    ws = wb.active
    ws.append(HEADERS)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _upload(client, rows=ROWS):
    r = client.post("/import", files={"file": ("orig.xlsx", _xlsx(rows), XLSX_MIME)})
    assert r.status_code == 200, r.text
    return r.json()["import_id"]


def _reimport(client, import_id, rows, filename="updated.xlsx"):
    return client.put(
        f"/imports/{import_id}/reimport",
        files={"file": (filename, _xlsx(rows), XLSX_MIME)},
    )


def _find_change(diff, cat_no, field):
    for c in diff["changed"]:
        if c["new"]["cat_no"] == cat_no or c["old"]["cat_no"] == cat_no:
            for f in c["fields"]:
                if f["field"] == field:
                    return f
    return None


def test_reimport_diff_no_snapshot_before_any_reimport(client):
    import_id = _upload(client)
    r = client.get(f"/imports/{import_id}/reimport-diff")
    assert r.status_code == 200
    body = r.json()
    assert body["no_snapshot"] is True
    assert body["has_changes"] is False


def test_reimport_diff_reports_source_change(client):
    import_id = _upload(client)
    # cat 1 price 500 -> 600 in the spreadsheet (a source change); cat 2 unchanged.
    new_rows = [
        [1, "Gallery A", "Sunset", "Jane Doe", "600", None, None, "Oil"],
        [2, "Gallery A", "Dawn", "John Smith RA", "1000", None, None, "Acrylic"],
    ]
    _reimport(client, import_id, new_rows, filename="march.xlsx")

    body = client.get(f"/imports/{import_id}/reimport-diff").json()
    assert body["no_snapshot"] is False
    assert body["has_changes"] is True
    assert body["snapshot"]["note"] == "march.xlsx"
    price = _find_change(body, "1", "price_numeric")
    assert price is not None
    assert price["causes"] == ["source"]


def test_snapshots_list_is_append_only_newest_first(client, db_session):
    from datetime import datetime, timedelta, timezone

    from backend.app.models.import_snapshot_model import ImportSnapshot

    import_id = _upload(client)
    _reimport(client, import_id, ROWS, filename="v1.xlsx")
    _reimport(client, import_id, ROWS, filename="v2.xlsx")

    # SQLite's CURRENT_TIMESTAMP is second-resolution, so two same-second
    # snapshots tie; force distinct created_at to test ordering deterministically.
    rows = (
        db_session.query(ImportSnapshot)
        .filter(ImportSnapshot.import_id == _uuid.UUID(import_id))
        .all()
    )
    assert len(rows) == 2  # append-only: a row per re-import
    by_note = {s.note: s for s in rows}
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    by_note["v1.xlsx"].created_at = base
    by_note["v2.xlsx"].created_at = base + timedelta(minutes=5)
    db_session.commit()

    snaps = client.get(f"/imports/{import_id}/snapshots").json()
    assert [s["note"] for s in snaps] == ["v2.xlsx", "v1.xlsx"]  # newest first
    assert all(s["kind"] == "pre_reimport" for s in snaps)


def test_specific_snapshot_diff(client):
    import_id = _upload(client)
    _reimport(client, import_id, ROWS, filename="v1.xlsx")
    snaps = client.get(f"/imports/{import_id}/snapshots").json()
    sid = snaps[0]["id"]
    r = client.get(f"/imports/{import_id}/snapshots/{sid}/diff")
    assert r.status_code == 200
    assert r.json()["snapshot"]["id"] == sid


def test_unknown_snapshot_is_404(client):
    import_id = _upload(client)
    r = client.get(f"/imports/{import_id}/snapshots/{_uuid.uuid4()}/diff")
    assert r.status_code == 404


def test_unknown_import_is_404(client):
    r = client.get(f"/imports/{_uuid.uuid4()}/reimport-diff")
    assert r.status_code == 404
