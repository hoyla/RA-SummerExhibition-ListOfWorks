"""Tests for the Artists' Index API routes."""

import io
import uuid

import pytest
from openpyxl import Workbook

from backend.app.models.import_model import Import
from backend.app.models.index_artist_model import IndexArtist
from backend.app.models.index_cat_number_model import IndexCatNumber
from backend.app.models.index_override_model import IndexArtistOverride
from backend.app.models.audit_log_model import AuditLog
from backend.app.models.known_artist_model import KnownArtist


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_index_xlsx(rows) -> io.BytesIO:
    """Create an in-memory .xlsx with standard Index headers."""
    wb = Workbook()
    ws = wb.active
    ws.append(
        ["Title", "First Name", "Last Name", "Quals", "Company", "Address 1", "Cat Nos"]
    )
    for row in rows:
        ws.append(list(row))
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _upload_index(client, rows=None, filename="index.xlsx"):
    """Upload an index spreadsheet and return the response."""
    if rows is None:
        rows = [
            (None, "Roger", "Adams", None, None, None, "101"),
            (None, "Cornelia", "Parker", "CBE RA", None, None, "205;300"),
        ]
    buf = _make_index_xlsx(rows)
    return client.post(
        "/index/import",
        files={
            "file": (
                filename,
                buf,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )


def _seed_index_import(db):
    """Seed an index import directly via the DB for unit-style tests."""
    imp = Import(filename="test.xlsx", product_type="artists_index")
    db.add(imp)
    db.flush()

    a1 = IndexArtist(
        import_id=imp.id,
        row_number=2,
        raw_last_name="Adams",
        raw_first_name="Roger",
        last_name="Adams",
        first_name="Roger",
        is_ra_member=False,
        is_company=False,
        sort_key="adams roger",
        include_in_export=True,
    )
    a2 = IndexArtist(
        import_id=imp.id,
        row_number=3,
        raw_last_name="Parker",
        raw_first_name="Cornelia",
        raw_quals="CBE RA",
        last_name="Parker",
        first_name="Cornelia",
        quals="CBE RA",
        is_ra_member=True,
        is_company=False,
        sort_key="parker cornelia",
        include_in_export=True,
    )
    db.add_all([a1, a2])
    db.flush()

    cn1 = IndexCatNumber(artist_id=a1.id, cat_no=101, source_row=2)
    cn2 = IndexCatNumber(artist_id=a2.id, cat_no=205, source_row=3)
    cn3 = IndexCatNumber(artist_id=a2.id, cat_no=300, source_row=3)
    db.add_all([cn1, cn2, cn3])
    db.commit()

    return imp, [a1, a2]


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


class TestUploadIndex:
    def test_upload_success(self, client):
        r = _upload_index(client)
        assert r.status_code == 200
        data = r.json()
        assert "import_id" in data

    def test_upload_creates_artists_index_import(self, client, db_session):
        r = _upload_index(client)
        import_id = uuid.UUID(r.json()["import_id"])
        imp = db_session.query(Import).filter(Import.id == import_id).first()
        assert imp is not None
        assert imp.product_type == "artists_index"

    def test_upload_invalid_file(self, client):
        buf = io.BytesIO(b"not an excel file")
        r = client.post(
            "/index/import",
            files={"file": ("bad.xlsx", buf, "application/octet-stream")},
        )
        assert r.status_code == 400

    def test_upload_missing_required_columns(self, client):
        wb = Workbook()
        ws = wb.active
        ws.append(["Title", "First Name"])  # Missing Last Name and Cat Nos
        ws.append(["", "Roger"])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        r = client.post(
            "/index/import",
            files={"file": ("bad.xlsx", buf, "application/octet-stream")},
        )
        assert r.status_code == 400
        assert "missing required" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# List imports
# ---------------------------------------------------------------------------


class TestListIndexImports:
    def test_empty_list(self, client):
        r = client.get("/index/imports")
        assert r.status_code == 200
        assert r.json() == []

    def test_lists_only_index_imports(self, client, db_session):
        # Create a LoW import (should be excluded)
        low = Import(filename="low.xlsx", product_type="list_of_works")
        db_session.add(low)
        db_session.commit()

        # Create an index import
        _upload_index(client)

        r = client.get("/index/imports")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["product_type"] == "artists_index"

    def test_includes_artist_count(self, client, db_session):
        resp = _upload_index(client)
        r = client.get("/index/imports")
        data = r.json()
        assert len(data) == 1
        assert data[0]["artist_count"] >= 1


# ---------------------------------------------------------------------------
# List artists
# ---------------------------------------------------------------------------


class TestListIndexArtists:
    def test_list_artists(self, client, db_session):
        imp, artists = _seed_index_import(db_session)
        r = client.get(f"/index/imports/{imp.id}/artists")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 2
        # Should be sorted by sort_key: adams before parker
        assert data[0]["last_name"] == "Adams"
        assert data[1]["last_name"] == "Parker"
        # index_name is a computed composite
        assert data[0]["index_name"] == "Adams, Roger"
        assert data[1]["index_name"] == "Parker, Cornelia cbe ra"

    def test_artists_include_cat_numbers(self, client, db_session):
        imp, artists = _seed_index_import(db_session)
        r = client.get(f"/index/imports/{imp.id}/artists")
        data = r.json()
        # Adams has 1 cat number
        assert len(data[0]["cat_numbers"]) == 1
        assert data[0]["cat_numbers"][0]["cat_no"] == 101
        # Parker has 2 cat numbers
        assert len(data[1]["cat_numbers"]) == 2

    def test_404_for_nonexistent_import(self, client):
        fake_id = str(uuid.uuid4())
        r = client.get(f"/index/imports/{fake_id}/artists")
        assert r.status_code == 404

    def test_404_for_low_import(self, client, db_session):
        """An existing LoW import should not be accessible via index routes."""
        low = Import(filename="low.xlsx", product_type="list_of_works")
        db_session.add(low)
        db_session.commit()
        r = client.get(f"/index/imports/{low.id}/artists")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


class TestExportIndex:
    def test_export_tagged_text(self, client, db_session):
        imp, _ = _seed_index_import(db_session)
        r = client.get(f"/index/imports/{imp.id}/export-tags")
        assert r.status_code == 200
        content = r.text
        assert "<ASCII-MAC>" in content
        assert "Adams" in content
        assert "Parker" in content

    def test_export_contains_cat_numbers(self, client, db_session):
        imp, _ = _seed_index_import(db_session)
        r = client.get(f"/index/imports/{imp.id}/export-tags")
        content = r.text
        assert "101" in content
        assert "205" in content
        assert "300" in content

    def test_export_404_for_missing_import(self, client):
        fake_id = str(uuid.uuid4())
        r = client.get(f"/index/imports/{fake_id}/export-tags")
        assert r.status_code == 404

    def test_export_letter_filter(self, client, db_session):
        """?letter=A should include only Adams, not Parker."""
        imp, _ = _seed_index_import(db_session)
        r = client.get(f"/index/imports/{imp.id}/export-tags?letter=A")
        assert r.status_code == 200
        content = r.text
        assert "Adams" in content
        assert "Parker" not in content

    def test_export_letter_filter_case_insensitive(self, client, db_session):
        """?letter=p (lowercase) should still match Parker."""
        imp, _ = _seed_index_import(db_session)
        r = client.get(f"/index/imports/{imp.id}/export-tags?letter=p")
        assert r.status_code == 200
        content = r.text
        assert "Parker" in content
        assert "Adams" not in content

    def test_export_letter_no_match_returns_header_only(self, client, db_session):
        """?letter=Z should return just the header, no entries."""
        imp, _ = _seed_index_import(db_session)
        r = client.get(f"/index/imports/{imp.id}/export-tags?letter=Z")
        assert r.status_code == 200
        content = r.text
        assert "<ASCII-MAC>" in content
        assert "Adams" not in content
        assert "Parker" not in content

    def test_export_escapes_non_mac_roman_chars(self, client, db_session):
        """Non-Mac-Roman characters should be escaped as <0x####>, not replaced with '?'."""
        imp = Import(filename="test.xlsx", product_type="artists_index")
        db_session.add(imp)
        db_session.flush()

        artist = IndexArtist(
            import_id=imp.id,
            row_number=2,
            raw_last_name="Garcí\u0101",  # ā (U+0101) is NOT in Mac Roman
            raw_first_name="René",
            last_name="Garcí\u0101",
            first_name="René",
            is_ra_member=False,
            is_company=False,
            sort_key="garcīa rené",
            include_in_export=True,
        )
        db_session.add(artist)
        db_session.flush()

        cn = IndexCatNumber(artist_id=artist.id, cat_no=42)
        db_session.add(cn)
        db_session.commit()

        r = client.get(f"/index/imports/{imp.id}/export-tags")
        assert r.status_code == 200
        decoded = r.content.decode("mac_roman")
        # ā (U+0101) must appear as <0x0101>, NOT as '?'
        assert "<0x0101>" in decoded
        assert "?" not in decoded.split("<ASCII-MAC>")[-1]  # no ? in body
        # é (U+00E9) IS in Mac Roman, so should appear normally
        assert "Ren\u00e9" in decoded


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


class TestDeleteIndex:
    def test_delete_import(self, client, db_session):
        imp, _ = _seed_index_import(db_session)
        r = client.delete(f"/index/imports/{imp.id}")
        assert r.status_code == 204

        # Should be gone
        assert db_session.query(Import).filter(Import.id == imp.id).first() is None

    def test_delete_cascades_artists(self, client, db_session):
        imp, artists = _seed_index_import(db_session)
        artist_ids = [a.id for a in artists]
        client.delete(f"/index/imports/{imp.id}")

        remaining = (
            db_session.query(IndexArtist).filter(IndexArtist.id.in_(artist_ids)).count()
        )
        assert remaining == 0

    def test_delete_404(self, client):
        fake_id = str(uuid.uuid4())
        r = client.delete(f"/index/imports/{fake_id}")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Exclude / include toggle
# ---------------------------------------------------------------------------


class TestExcludeIndexArtist:
    def test_exclude_artist(self, client, db_session):
        imp, artists = _seed_index_import(db_session)
        artist = artists[0]
        r = client.patch(
            f"/index/imports/{imp.id}/artists/{artist.id}/exclude?exclude=true",
        )
        assert r.status_code == 200
        data = r.json()
        assert data["include_in_export"] is False

    def test_include_artist(self, client, db_session):
        imp, artists = _seed_index_import(db_session)
        artist = artists[0]
        # Exclude first
        client.patch(
            f"/index/imports/{imp.id}/artists/{artist.id}/exclude?exclude=true",
        )
        # Re-include
        r = client.patch(
            f"/index/imports/{imp.id}/artists/{artist.id}/exclude?exclude=false",
        )
        assert r.status_code == 200
        assert r.json()["include_in_export"] is True

    def test_exclude_creates_audit_log(self, client, db_session):
        imp, artists = _seed_index_import(db_session)
        artist = artists[0]
        client.patch(
            f"/index/imports/{imp.id}/artists/{artist.id}/exclude?exclude=true",
        )
        log = db_session.query(AuditLog).filter(AuditLog.import_id == imp.id).first()
        assert log is not None
        assert log.action == "index_artist_excluded"

    def test_exclude_excluded_is_noop(self, client, db_session):
        imp, artists = _seed_index_import(db_session)
        artist = artists[0]
        # Exclude
        client.patch(
            f"/index/imports/{imp.id}/artists/{artist.id}/exclude?exclude=true",
        )
        # Exclude again — should be a no-op (no extra audit log)
        client.patch(
            f"/index/imports/{imp.id}/artists/{artist.id}/exclude?exclude=true",
        )
        logs = db_session.query(AuditLog).filter(AuditLog.import_id == imp.id).all()
        assert len(logs) == 1

    def test_excluded_artist_not_in_export(self, client, db_session):
        imp, artists = _seed_index_import(db_session)
        artist = artists[0]  # Adams
        client.patch(
            f"/index/imports/{imp.id}/artists/{artist.id}/exclude?exclude=true",
        )
        r = client.get(f"/index/imports/{imp.id}/export-tags")
        content = r.text
        assert "Adams" not in content
        assert "Parker" in content

    def test_404_for_wrong_artist(self, client, db_session):
        imp, _ = _seed_index_import(db_session)
        fake_id = str(uuid.uuid4())
        r = client.patch(
            f"/index/imports/{imp.id}/artists/{fake_id}/exclude?exclude=true",
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Company toggle
# ---------------------------------------------------------------------------


class TestCompanyToggle:
    def test_set_company(self, client, db_session):
        imp, artists = _seed_index_import(db_session)
        artist = artists[0]  # Adams — not a company
        assert artist.is_company is False
        r = client.patch(
            f"/index/imports/{imp.id}/artists/{artist.id}/company?is_company=true",
        )
        assert r.status_code == 200
        assert r.json()["is_company"] is True
        assert r.json()["is_company_auto"] is False  # auto-detected was False

    def test_set_company_creates_override_row(self, client, db_session):
        imp, artists = _seed_index_import(db_session)
        artist = artists[0]
        client.patch(
            f"/index/imports/{imp.id}/artists/{artist.id}/company?is_company=true",
        )
        override = (
            db_session.query(IndexArtistOverride)
            .filter(IndexArtistOverride.artist_id == artist.id)
            .first()
        )
        assert override is not None
        assert override.is_company_override is True

    def test_set_company_does_not_mutate_artist(self, client, db_session):
        imp, artists = _seed_index_import(db_session)
        artist = artists[0]
        client.patch(
            f"/index/imports/{imp.id}/artists/{artist.id}/company?is_company=true",
        )
        db_session.refresh(artist)
        assert artist.is_company is False  # original auto-detected value preserved

    def test_unset_company(self, client, db_session):
        imp, artists = _seed_index_import(db_session)
        artist = artists[0]
        # Set as company first
        client.patch(
            f"/index/imports/{imp.id}/artists/{artist.id}/company?is_company=true",
        )
        # Unset
        r = client.patch(
            f"/index/imports/{imp.id}/artists/{artist.id}/company?is_company=false",
        )
        assert r.status_code == 200
        assert r.json()["is_company"] is False

    def test_override_reflected_in_artist_listing(self, client, db_session):
        imp, artists = _seed_index_import(db_session)
        artist = artists[0]  # Adams — auto-detected as not company
        client.patch(
            f"/index/imports/{imp.id}/artists/{artist.id}/company?is_company=true",
        )
        r = client.get(f"/index/imports/{imp.id}/artists")
        adams = [a for a in r.json() if a["last_name"] == "Adams"][0]
        assert adams["is_company"] is True
        assert adams["is_company_auto"] is False

    def test_company_toggle_creates_audit_log(self, client, db_session):
        imp, artists = _seed_index_import(db_session)
        artist = artists[0]
        client.patch(
            f"/index/imports/{imp.id}/artists/{artist.id}/company?is_company=true",
        )
        log = db_session.query(AuditLog).filter(AuditLog.import_id == imp.id).first()
        assert log is not None
        assert log.action == "index_artist_company_set"
        assert log.field == "is_company_override"

    def test_company_unset_audit_log(self, client, db_session):
        imp, artists = _seed_index_import(db_session)
        artist = artists[0]
        # Set then unset
        client.patch(
            f"/index/imports/{imp.id}/artists/{artist.id}/company?is_company=true",
        )
        client.patch(
            f"/index/imports/{imp.id}/artists/{artist.id}/company?is_company=false",
        )
        logs = db_session.query(AuditLog).filter(AuditLog.import_id == imp.id).all()
        assert len(logs) == 2
        assert logs[1].action == "index_artist_company_unset"

    def test_company_noop_no_extra_audit(self, client, db_session):
        imp, artists = _seed_index_import(db_session)
        artist = artists[0]
        # Already not a company — setting false again is noop
        client.patch(
            f"/index/imports/{imp.id}/artists/{artist.id}/company?is_company=false",
        )
        logs = db_session.query(AuditLog).filter(AuditLog.import_id == imp.id).all()
        assert len(logs) == 0

    def test_company_404_for_wrong_artist(self, client, db_session):
        imp, _ = _seed_index_import(db_session)
        fake_id = str(uuid.uuid4())
        r = client.patch(
            f"/index/imports/{imp.id}/artists/{fake_id}/company?is_company=true",
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Warnings
# ---------------------------------------------------------------------------


class TestIndexWarnings:
    def test_warnings_empty(self, client, db_session):
        imp, _ = _seed_index_import(db_session)
        r = client.get(f"/index/imports/{imp.id}/warnings")
        assert r.status_code == 200
        assert r.json() == []

    def test_warnings_404(self, client):
        fake_id = str(uuid.uuid4())
        r = client.get(f"/index/imports/{fake_id}/warnings")
        assert r.status_code == 404

    def test_warnings_include_row_number_and_artist_id(self, client, db_session):
        """Warning response should include row_number & artist_id for linkable warnings."""
        from backend.app.models.validation_warning_model import ValidationWarning

        imp, artists = _seed_index_import(db_session)
        # Manually add a warning referencing row 2 (same row_number as artist Adams)
        db_session.add(
            ValidationWarning(
                import_id=imp.id,
                work_id=None,
                warning_type="test_warning",
                message="Row 2: Something about Adams",
            )
        )
        db_session.commit()

        r = client.get(f"/index/imports/{imp.id}/warnings")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["row_number"] == 2
        assert data[0]["artist_id"] == str(artists[0].id)

    def test_warnings_no_row_number_for_import_level(self, client, db_session):
        """Import-level warnings (no 'Row N:' prefix) should have null row_number."""
        from backend.app.models.validation_warning_model import ValidationWarning

        imp, _ = _seed_index_import(db_session)
        db_session.add(
            ValidationWarning(
                import_id=imp.id,
                work_id=None,
                warning_type="duplicate_filename",
                message="A previous import with filename 'test.xlsx' already exists",
            )
        )
        db_session.commit()

        r = client.get(f"/index/imports/{imp.id}/warnings")
        data = r.json()
        assert len(data) == 1
        assert data[0]["row_number"] is None
        assert data[0]["artist_id"] is None


# ---------------------------------------------------------------------------
# Merge / Unmerge
# ---------------------------------------------------------------------------


class TestMergeUnmerge:
    """Test duplicate-name merging and the unmerge endpoint."""

    def test_import_merges_duplicate_names(self, client, db_session):
        """Two rows with same name + no courtesy -> merged into one artist."""
        rows = [
            (None, "John", "Smith", None, None, None, "101"),
            (None, "John", "Smith", None, None, None, "205"),
        ]
        r = _upload_index(client, rows)
        assert r.status_code == 200
        import_id = r.json()["import_id"]

        artists = client.get(f"/index/imports/{import_id}/artists").json()
        assert len(artists) == 1

        a = artists[0]
        cat_nos = sorted(cn["cat_no"] for cn in a["cat_numbers"])
        assert cat_nos == [101, 205]
        # source_row should track where each cat came from
        source_rows = sorted(cn["source_row"] for cn in a["cat_numbers"])
        assert source_rows == [2, 3]

    def test_import_merge_creates_warning(self, client, db_session):
        """Merging duplicate names should produce a linkable validation warning."""
        rows = [
            (None, "John", "Smith", None, None, None, "101"),
            (None, "John", "Smith", None, None, None, "205"),
        ]
        r = _upload_index(client, rows)
        import_id = r.json()["import_id"]

        warnings = client.get(f"/index/imports/{import_id}/warnings").json()
        merge_warnings = [
            w for w in warnings if w["warning_type"] == "duplicate_name_merged"
        ]
        assert len(merge_warnings) == 1
        assert "Rows 2, 3" in merge_warnings[0]["message"]
        assert "John Smith" in merge_warnings[0]["message"]

        # The "Rows N, M:" format should still parse a row_number and link
        # to the merged artist
        assert merge_warnings[0]["row_number"] == 2
        artists = client.get(f"/index/imports/{import_id}/artists").json()
        assert merge_warnings[0]["artist_id"] == artists[0]["id"]

    def test_merged_from_rows_in_artist_response(self, client, db_session):
        """Artists merged from multiple rows should have merged_from_rows."""
        rows = [
            (None, "John", "Smith", None, None, None, "101"),
            (None, "John", "Smith", None, None, None, "205"),
        ]
        r = _upload_index(client, rows)
        import_id = r.json()["import_id"]

        artists = client.get(f"/index/imports/{import_id}/artists").json()
        assert len(artists) == 1
        assert artists[0]["merged_from_rows"] == [2, 3]

    def test_non_merged_artist_has_null_merged_from_rows(self, client, db_session):
        """An artist from a single row should not have merged_from_rows."""
        rows = [
            (None, "John", "Smith", None, None, None, "101"),
            (None, "Jane", "Doe", None, None, None, "205"),
        ]
        r = _upload_index(client, rows)
        import_id = r.json()["import_id"]

        artists = client.get(f"/index/imports/{import_id}/artists").json()
        assert len(artists) == 2
        for a in artists:
            assert a["merged_from_rows"] is None

    def test_unmerge_splits_artist(self, client, db_session):
        """POST unmerge should split a merged artist into separate entries."""
        rows = [
            (None, "John", "Smith", None, None, None, "101"),
            (None, "John", "Smith", None, None, None, "205"),
        ]
        r = _upload_index(client, rows)
        import_id = r.json()["import_id"]

        artists = client.get(f"/index/imports/{import_id}/artists").json()
        assert len(artists) == 1
        artist_id = artists[0]["id"]

        # Unmerge
        r = client.post(f"/index/imports/{import_id}/artists/{artist_id}/unmerge")
        assert r.status_code == 200
        resp = r.json()
        assert len(resp["new_artist_ids"]) == 1

        # Now should have 2 artists with 1 cat number each
        artists = client.get(f"/index/imports/{import_id}/artists").json()
        assert len(artists) == 2
        for a in artists:
            assert len(a["cat_numbers"]) == 1
            assert a["merged_from_rows"] is None

        # Verify cat numbers distributed correctly
        all_cats = {a["cat_numbers"][0]["cat_no"] for a in artists}
        assert all_cats == {101, 205}

    def test_unmerge_preserves_row_numbers(self, client, db_session):
        """Unmerged artists should have correct row_number values."""
        rows = [
            (None, "John", "Smith", None, None, None, "101"),
            (None, "John", "Smith", None, None, None, "205"),
        ]
        r = _upload_index(client, rows)
        import_id = r.json()["import_id"]
        artists = client.get(f"/index/imports/{import_id}/artists").json()
        artist_id = artists[0]["id"]

        client.post(f"/index/imports/{import_id}/artists/{artist_id}/unmerge")

        artists = client.get(f"/index/imports/{import_id}/artists").json()
        row_numbers = sorted(a["row_number"] for a in artists)
        assert row_numbers == [2, 3]

    def test_unmerge_non_merged_returns_400(self, client, db_session):
        """Trying to unmerge an artist that wasn't merged should return 400."""
        imp, artists = _seed_index_import(db_session)
        artist_id = str(artists[0].id)

        r = client.post(f"/index/imports/{imp.id}/artists/{artist_id}/unmerge")
        assert r.status_code == 400
        assert "not merged" in r.json()["detail"].lower()

    def test_unmerge_three_rows(self, client, db_session):
        """Unmerging an artist merged from 3 rows creates 2 new entries."""
        rows = [
            (None, "John", "Smith", None, None, None, "101"),
            (None, "John", "Smith", None, None, None, "205"),
            (None, "John", "Smith", None, None, None, "310"),
        ]
        r = _upload_index(client, rows)
        import_id = r.json()["import_id"]

        artists = client.get(f"/index/imports/{import_id}/artists").json()
        assert len(artists) == 1
        assert sorted(artists[0]["merged_from_rows"]) == [2, 3, 4]
        artist_id = artists[0]["id"]

        r = client.post(f"/index/imports/{import_id}/artists/{artist_id}/unmerge")
        assert r.status_code == 200
        assert len(r.json()["new_artist_ids"]) == 2

        artists = client.get(f"/index/imports/{import_id}/artists").json()
        assert len(artists) == 3
        all_cats = sorted(cn["cat_no"] for a in artists for cn in a["cat_numbers"])
        assert all_cats == [101, 205, 310]

    def test_courtesy_rows_not_merged(self, client, db_session):
        """Rows with an address (courtesy) should stay as separate entries."""
        rows = [
            (None, "John", "Smith", None, None, None, "101"),
            (None, "John", "Smith", None, None, "Courtesy of Gallery", "205"),
        ]
        r = _upload_index(client, rows)
        import_id = r.json()["import_id"]

        artists = client.get(f"/index/imports/{import_id}/artists").json()
        # Should be 2 separate entries -- no merge because one has courtesy
        assert len(artists) == 2
        for a in artists:
            assert a["merged_from_rows"] is None


# ---------------------------------------------------------------------------
# Auto-resolved & override fields in artist listing
# ---------------------------------------------------------------------------


class TestArtistListingAutoResolved:
    """Test that the artist listing includes auto_resolved and override fields."""

    def test_no_override_fields_are_null(self, client, db_session):
        """Without an override, auto_resolved and override should be null."""
        imp, artists = _seed_index_import(db_session)
        r = client.get(f"/index/imports/{imp.id}/artists")
        assert r.status_code == 200
        for a in r.json():
            assert a["auto_resolved"] is None
            assert a["override"] is None
            assert a["has_override"] is False

    def test_with_override_returns_auto_resolved_and_override(self, client, db_session):
        """When an override is set, auto_resolved shows pre-override values
        and override contains the override record."""
        imp, artists = _seed_index_import(db_session)
        artist = artists[0]  # Adams, Roger

        # Set an override changing the first name
        client.put(
            f"/index/imports/{imp.id}/artists/{artist.id}/override",
            json={"first_name_override": "Bob"},
        )

        r = client.get(f"/index/imports/{imp.id}/artists")
        adams = [a for a in r.json() if a["id"] == str(artist.id)][0]

        assert adams["has_override"] is True
        assert adams["override"] is not None
        assert adams["override"]["first_name_override"] == "Bob"

        assert adams["auto_resolved"] is not None
        # Auto-resolved should show the original normalised first name
        assert adams["auto_resolved"]["first_name"] == "Roger"

        # Effective value should reflect the override
        assert adams["first_name"] == "Bob"

    def test_auto_resolved_includes_known_artist(self, client, db_session):
        """auto_resolved should include known artist resolution but not user override."""
        imp, artists = _seed_index_import(db_session)
        artist = artists[0]  # Adams, Roger

        # Create a known artist rule that changes Roger -> Rodger
        ka = KnownArtist(
            match_first_name="Roger",
            match_last_name="Adams",
            resolved_first_name="Rodger",
            resolved_last_name="Adams",
        )
        db_session.add(ka)
        db_session.commit()

        # Set an override on top of the known artist
        client.put(
            f"/index/imports/{imp.id}/artists/{artist.id}/override",
            json={"first_name_override": "Bob"},
        )

        r = client.get(f"/index/imports/{imp.id}/artists")
        adams = [a for a in r.json() if a["id"] == str(artist.id)][0]

        # Auto-resolved should include known artist (Rodger) but NOT override
        assert adams["auto_resolved"]["first_name"] == "Rodger"

        # Effective value should be the override (Bob)
        assert adams["first_name"] == "Bob"

    def test_non_overridden_artist_unaffected(self, client, db_session):
        """Artists without overrides should remain unaffected when others have them."""
        imp, artists = _seed_index_import(db_session)

        # Override Adams only
        client.put(
            f"/index/imports/{imp.id}/artists/{artists[0].id}/override",
            json={"first_name_override": "Bob"},
        )

        r = client.get(f"/index/imports/{imp.id}/artists")
        parker = [a for a in r.json() if a["last_name"] == "Parker"][0]
        assert parker["auto_resolved"] is None
        assert parker["override"] is None
        assert parker["has_override"] is False
