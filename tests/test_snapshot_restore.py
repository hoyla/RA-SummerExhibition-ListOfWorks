"""Tests for snapshot restore / undo.

  POST /imports/{id}/snapshots/{sid}/restore  — replace current data with a snapshot

Restore reinstates the exact prior state (raw + normalised + overrides + flags),
takes a pre_restore snapshot first (so it's itself reversible), and is audited.
"""

import io
import uuid as _uuid

import pytest
from openpyxl import Workbook

from backend.app.models.audit_log_model import AuditLog
from backend.app.models.import_snapshot_model import ImportSnapshot

client = pytest.fixture(name="client")(lambda client_lenient: client_lenient)

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
HEADERS = ["Cat No", "Gallery", "Title", "Artist", "Price", "Edition", "Artwork", "Medium"]
ORIG = [
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


def _upload(client, rows):
    r = client.post("/import", files={"file": ("orig.xlsx", _xlsx(rows), XLSX_MIME)})
    assert r.status_code == 200, r.text
    return r.json()["import_id"]


def _reimport(client, import_id, rows, filename="updated.xlsx"):
    r = client.put(
        f"/imports/{import_id}/reimport",
        files={"file": (filename, _xlsx(rows), XLSX_MIME)},
    )
    assert r.status_code == 200, r.text
    return r


def _works(client, import_id):
    sections = client.get(f"/imports/{import_id}/sections").json()
    return {w["raw_cat_no"]: w for s in sections for w in s["works"]}


def _setup_polished_then_reimported(client):
    """Upload, add an override + exclusion, then re-import with a price change
    and an added work. Returns (import_id, pre_reimport_snapshot_id)."""
    import_id = _upload(client, ORIG)
    works = _works(client, import_id)
    client.put(
        f"/imports/{import_id}/works/{works['2']['id']}/override",
        json={"title_override": "Custom Dawn"},
    )
    client.patch(f"/imports/{import_id}/works/{works['1']['id']}/exclude?exclude=true")

    new_rows = [
        [1, "Gallery A", "Sunset", "Jane Doe", "600", None, None, "Oil"],  # price changed
        [2, "Gallery A", "Dawn", "John Smith RA", "1000", None, None, "Acrylic"],
        [3, "Gallery A", "Noon", "Alice", "NFS", None, None, None],  # added
    ]
    _reimport(client, import_id, new_rows)

    snaps = client.get(f"/imports/{import_id}/snapshots").json()
    assert len(snaps) == 1  # the pre-reimport snapshot
    return import_id, snaps[0]["id"]


def test_restore_reinstates_prior_state(client):
    import_id, sid = _setup_polished_then_reimported(client)

    # Sanity: the re-import did change things.
    post = _works(client, import_id)
    assert post["1"]["price_numeric"] == 600.0
    assert "3" in post

    r = client.post(f"/imports/{import_id}/snapshots/{sid}/restore")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["restored"] is True
    assert body["works"] == 2

    w = _works(client, import_id)
    assert set(w.keys()) == {"1", "2"}  # the added cat 3 is gone
    assert w["1"]["price_numeric"] == 500.0  # price reverted
    assert w["1"]["include_in_export"] is False  # exclusion reinstated
    assert w["2"]["override"]["title_override"] == "Custom Dawn"  # override reinstated


def test_restore_takes_pre_restore_snapshot_and_audits(client, db_session):
    import_id, sid = _setup_polished_then_reimported(client)
    client.post(f"/imports/{import_id}/snapshots/{sid}/restore")

    iid = _uuid.UUID(import_id)
    kinds = [
        s.kind
        for s in db_session.query(ImportSnapshot).filter(ImportSnapshot.import_id == iid).all()
    ]
    assert "pre_restore" in kinds  # current state captured before the restore

    logs = (
        db_session.query(AuditLog)
        .filter(AuditLog.import_id == iid, AuditLog.action == "snapshot_restore")
        .all()
    )
    assert len(logs) == 1


def test_restore_is_reversible(client):
    """Restoring the pre_restore snapshot returns to the post-reimport state."""
    import_id, sid = _setup_polished_then_reimported(client)
    client.post(f"/imports/{import_id}/snapshots/{sid}/restore")
    # The restore captured a pre_restore snapshot of the post-reimport state.
    # Select it by kind (not "newest" — SQLite's second-resolution timestamps
    # tie when the whole flow runs in milliseconds).
    snaps = client.get(f"/imports/{import_id}/snapshots").json()
    pre_restore_id = next(s["id"] for s in snaps if s["kind"] == "pre_restore")

    client.post(f"/imports/{import_id}/snapshots/{pre_restore_id}/restore")
    w = _works(client, import_id)
    assert "3" in w  # the added work is back
    assert w["1"]["price_numeric"] == 600.0  # price change is back


def test_restore_unknown_snapshot_is_404(client):
    import_id = _upload(client, ORIG)
    r = client.post(f"/imports/{import_id}/snapshots/{_uuid.uuid4()}/restore")
    assert r.status_code == 404


def test_restore_unknown_import_is_404(client):
    r = client.post(f"/imports/{_uuid.uuid4()}/snapshots/{_uuid.uuid4()}/restore")
    assert r.status_code == 404
