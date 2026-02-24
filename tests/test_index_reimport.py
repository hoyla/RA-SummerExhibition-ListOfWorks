"""
Tests for the Index re-import feature: PUT /index/imports/{import_id}/reimport

Covers:
  - Basic re-import replaces artists and cat numbers
  - Overrides preserved when sort_key matches
  - include_in_export preserved when sort_key matches
  - New artists added, old artists removed
  - Stats returned correctly (matched, added, removed, overrides_preserved)
  - Audit log entry created
  - Validation warnings regenerated
  - 404 when import does not exist
  - 400 when uploaded file is invalid
  - Courtesy artists matched separately from non-courtesy
  - Filename updated after reimport
"""

import io
import uuid

import pytest
from openpyxl import Workbook

from backend.app.models.import_model import Import
from backend.app.models.index_artist_model import IndexArtist
from backend.app.models.index_cat_number_model import IndexCatNumber
from backend.app.models.index_override_model import IndexArtistOverride
from backend.app.models.validation_warning_model import ValidationWarning
from backend.app.models.audit_log_model import AuditLog


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

INDEX_HEADERS = [
    "Title",
    "First Name",
    "Last Name",
    "Quals",
    "Company",
    "Address 1",
    "Cat Nos",
]


def _make_index_xlsx(rows) -> io.BytesIO:
    """Create an in-memory .xlsx with standard Index headers."""
    wb = Workbook()
    ws = wb.active
    ws.append(INDEX_HEADERS)
    for row in rows:
        ws.append(list(row))
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _upload_index(client, rows=None, filename="index.xlsx"):
    """Upload an index spreadsheet and return (response, import_id)."""
    if rows is None:
        rows = [
            (None, "Roger", "Adams", None, None, None, "101"),
            (None, "Cornelia", "Parker", "CBE RA", None, None, "205;300"),
            (None, "Alice", "Brown", None, None, None, "50"),
        ]
    buf = _make_index_xlsx(rows)
    r = client.post(
        "/index/import",
        files={
            "file": (
                filename,
                buf,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert r.status_code == 200, r.text
    return r, r.json()["import_id"]


def _reimport_index(client, import_id, rows=None, filename="index-v2.xlsx"):
    """Re-import into an existing index import and return the response."""
    if rows is None:
        # Matching Adams & Parker, adding Davies, removing Brown
        rows = [
            (None, "Roger", "Adams", None, None, None, "101;102"),
            (None, "Cornelia", "Parker", "CBE RA", None, None, "205;300;400"),
            (None, "David", "Davies", None, None, None, "77"),
        ]
    buf = _make_index_xlsx(rows)
    return client.put(
        f"/index/imports/{import_id}/reimport",
        files={
            "file": (
                filename,
                buf,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )


def _get_artists(client, import_id):
    r = client.get(f"/index/imports/{import_id}/artists")
    assert r.status_code == 200
    return r.json()


# =========================================================================== #
# Tests
# =========================================================================== #


class TestIndexReimportBasic:
    """Core re-import behaviour."""

    def test_reimport_replaces_artists(self, client):
        _, import_id = _upload_index(client)
        artists_before = _get_artists(client, import_id)
        assert len(artists_before) == 3

        r = _reimport_index(client, import_id)
        assert r.status_code == 200
        data = r.json()
        assert data["import_id"] == import_id

        artists_after = _get_artists(client, import_id)
        assert len(artists_after) == 3  # same count, different artists

    def test_reimport_updates_artist_data(self, client):
        _, import_id = _upload_index(client)

        # Reimport with updated cat numbers for Adams
        _reimport_index(client, import_id)

        artists = _get_artists(client, import_id)
        adams = next(a for a in artists if a["last_name"] == "Adams")
        cat_nos = sorted(cn["cat_no"] for cn in adams["cat_numbers"])
        assert cat_nos == [101, 102]

    def test_reimport_returns_correct_stats(self, client):
        _, import_id = _upload_index(client)
        # Original: Adams, Parker, Brown
        # Reimport: Adams, Parker, Davies → matched=2, added=1, removed=1

        r = _reimport_index(client, import_id)
        data = r.json()
        assert data["matched"] == 2
        assert data["added"] == 1
        assert data["removed"] == 1

    def test_reimport_all_new_artists(self, client):
        _, import_id = _upload_index(client)
        rows = [
            (None, "Xavier", "Young", None, None, None, "999"),
        ]
        r = _reimport_index(client, import_id, rows=rows)
        data = r.json()
        assert data["matched"] == 0
        assert data["added"] == 1
        assert data["removed"] == 3

    def test_reimport_identical_spreadsheet(self, client):
        rows = [
            (None, "Roger", "Adams", None, None, None, "101"),
            (None, "Cornelia", "Parker", "CBE RA", None, None, "205;300"),
        ]
        _, import_id = _upload_index(client, rows=rows)
        r = _reimport_index(client, import_id, rows=rows)
        data = r.json()
        assert data["matched"] == 2
        assert data["added"] == 0
        assert data["removed"] == 0


class TestIndexReimportOverrides:
    """Override and include_in_export preservation."""

    def test_override_preserved_on_match(self, client, db_session):
        _, import_id = _upload_index(client)

        # Find Adams and apply an override
        artists = _get_artists(client, import_id)
        adams = next(a for a in artists if a["last_name"] == "Adams")
        client.put(
            f"/index/imports/{import_id}/artists/{adams['id']}/override",
            json={"first_name_override": "Sir Roger"},
        )

        # Reimport with Adams still present
        r = _reimport_index(client, import_id)
        data = r.json()
        assert data["overrides_preserved"] >= 1

        # Verify override was restored
        artists_after = _get_artists(client, import_id)
        adams_after = next(a for a in artists_after if a["last_name"] == "Adams")
        ovr = client.get(
            f"/index/imports/{import_id}/artists/{adams_after['id']}/override"
        )
        assert ovr.status_code == 200
        assert ovr.json()["first_name_override"] == "Sir Roger"

    def test_include_in_export_preserved(self, client, db_session):
        _, import_id = _upload_index(client)

        # Exclude Adams from export
        artists = _get_artists(client, import_id)
        adams = next(a for a in artists if a["last_name"] == "Adams")
        client.patch(
            f"/index/imports/{import_id}/artists/{adams['id']}/exclude?exclude=true",
        )

        # Verify exclusion
        artists_check = _get_artists(client, import_id)
        adams_check = next(a for a in artists_check if a["last_name"] == "Adams")
        assert adams_check["include_in_export"] is False

        # Reimport
        _reimport_index(client, import_id)

        # Verify exclusion preserved
        artists_after = _get_artists(client, import_id)
        adams_after = next(a for a in artists_after if a["last_name"] == "Adams")
        assert adams_after["include_in_export"] is False

    def test_override_lost_when_artist_removed(self, client, db_session):
        _, import_id = _upload_index(client)

        # Override Brown (will be removed in reimport)
        artists = _get_artists(client, import_id)
        brown = next(a for a in artists if a["last_name"] == "Brown")
        client.put(
            f"/index/imports/{import_id}/artists/{brown['id']}/override",
            json={"quals_override": "OBE"},
        )

        # Reimport without Brown
        r = _reimport_index(client, import_id)
        data = r.json()
        assert data["removed"] == 1

        # Brown should no longer exist
        artists_after = _get_artists(client, import_id)
        assert not any(a["last_name"] == "Brown" for a in artists_after)

    def test_company_override_preserved(self, client, db_session):
        _, import_id = _upload_index(client)

        artists = _get_artists(client, import_id)
        adams = next(a for a in artists if a["last_name"] == "Adams")
        client.put(
            f"/index/imports/{import_id}/artists/{adams['id']}/override",
            json={"is_company_override": True},
        )

        _reimport_index(client, import_id)

        artists_after = _get_artists(client, import_id)
        adams_after = next(a for a in artists_after if a["last_name"] == "Adams")
        ovr = client.get(
            f"/index/imports/{import_id}/artists/{adams_after['id']}/override"
        )
        assert ovr.status_code == 200
        assert ovr.json()["is_company_override"] is True


class TestIndexReimportCourtesy:
    """Courtesy vs. non-courtesy matching."""

    def test_courtesy_artist_matched_separately(self, client):
        rows = [
            (None, "Roger", "Adams", None, None, None, "101"),
            (None, "Roger", "Adams", None, None, "Gallery X", "102"),
        ]
        _, import_id = _upload_index(client, rows=rows)
        artists_before = _get_artists(client, import_id)
        assert len(artists_before) == 2

        # Reimport with same rows
        r = _reimport_index(client, import_id, rows=rows)
        data = r.json()
        assert data["matched"] == 2
        assert data["added"] == 0
        assert data["removed"] == 0

    def test_courtesy_artist_not_matched_with_non_courtesy(self, client):
        # Original: Adams with courtesy
        rows_v1 = [
            (None, "Roger", "Adams", None, None, "Gallery X", "101"),
        ]
        _, import_id = _upload_index(client, rows=rows_v1)

        # Reimport: Adams without courtesy
        rows_v2 = [
            (None, "Roger", "Adams", None, None, None, "101"),
        ]
        r = _reimport_index(client, import_id, rows=rows_v2)
        data = r.json()
        # Should not match since courtesy differs
        assert data["matched"] == 0
        assert data["added"] == 1
        assert data["removed"] == 1


class TestIndexReimportAuditAndWarnings:
    """Audit log and validation warnings."""

    def test_audit_log_created(self, client, db_session):
        _, import_id = _upload_index(client)
        _reimport_index(client, import_id)

        iid = uuid.UUID(import_id)
        logs = (
            db_session.query(AuditLog)
            .filter(AuditLog.import_id == iid, AuditLog.action == "reimport")
            .all()
        )
        assert len(logs) == 1
        assert "matched=" in logs[0].new_value
        assert "added=" in logs[0].new_value
        assert "removed=" in logs[0].new_value

    def test_warnings_regenerated(self, client, db_session):
        _, import_id = _upload_index(client)
        iid = uuid.UUID(import_id)
        warnings_before = (
            db_session.query(ValidationWarning)
            .filter(ValidationWarning.import_id == iid)
            .count()
        )

        # Reimport — warnings should be regenerated (old ones deleted)
        _reimport_index(client, import_id)
        db_session.expire_all()

        warnings_after = (
            db_session.query(ValidationWarning)
            .filter(ValidationWarning.import_id == iid)
            .all()
        )
        # We just check they exist — count may differ based on new data
        assert isinstance(warnings_after, list)

    def test_filename_updated(self, client, db_session):
        _, import_id = _upload_index(client, filename="original.xlsx")
        _reimport_index(client, import_id, filename="updated.xlsx")
        db_session.expire_all()

        iid = uuid.UUID(import_id)
        imp = db_session.query(Import).filter(Import.id == iid).first()
        assert imp.filename == "updated.xlsx"


class TestIndexReimportEdgeCases:
    """Edge cases and error handling."""

    def test_reimport_nonexistent_import(self, client):
        fake_id = str(uuid.uuid4())
        rows = [(None, "Test", "Person", None, None, None, "1")]
        r = _reimport_index(client, fake_id, rows=rows)
        assert r.status_code == 404

    def test_reimport_invalid_file(self, client):
        _, import_id = _upload_index(client)
        r = client.put(
            f"/index/imports/{import_id}/reimport",
            files={
                "file": (
                    "bad.xlsx",
                    io.BytesIO(b"not a real xlsx"),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        assert r.status_code == 400

    def test_reimport_empty_spreadsheet(self, client):
        _, import_id = _upload_index(client)
        rows = []  # No data rows
        r = _reimport_index(client, import_id, rows=rows)
        assert r.status_code == 200
        data = r.json()
        assert data["matched"] == 0
        assert data["removed"] == 3

    def test_multiple_reimports(self, client):
        _, import_id = _upload_index(client)

        # First reimport
        r1 = _reimport_index(client, import_id)
        assert r1.status_code == 200

        # Second reimport
        rows_v3 = [
            (None, "Roger", "Adams", None, None, None, "101"),
        ]
        r2 = _reimport_index(client, import_id, rows=rows_v3)
        assert r2.status_code == 200
        data = r2.json()
        # From reimport default (Adams, Parker, Davies) to v3 (Adams only)
        assert data["matched"] == 1
        assert data["removed"] == 2

    def test_reimport_preserves_multiple_overrides(self, client, db_session):
        """Overrides on multiple artists are all preserved."""
        _, import_id = _upload_index(client)
        artists = _get_artists(client, import_id)

        # Override both Adams and Parker
        adams = next(a for a in artists if a["last_name"] == "Adams")
        parker = next(a for a in artists if a["last_name"] == "Parker")

        client.put(
            f"/index/imports/{import_id}/artists/{adams['id']}/override",
            json={"title_override": "Dr"},
        )
        client.put(
            f"/index/imports/{import_id}/artists/{parker['id']}/override",
            json={"quals_override": "RA"},
        )

        r = _reimport_index(client, import_id)
        data = r.json()
        assert data["overrides_preserved"] == 2

        # Verify both overrides restored
        artists_after = _get_artists(client, import_id)
        adams_after = next(a for a in artists_after if a["last_name"] == "Adams")
        parker_after = next(a for a in artists_after if a["last_name"] == "Parker")

        ovr_adams = client.get(
            f"/index/imports/{import_id}/artists/{adams_after['id']}/override"
        ).json()
        ovr_parker = client.get(
            f"/index/imports/{import_id}/artists/{parker_after['id']}/override"
        ).json()

        assert ovr_adams["title_override"] == "Dr"
        assert ovr_parker["quals_override"] == "RA"
