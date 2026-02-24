"""
Tests for the Artists' Index export diff / snapshot feature.

Covers:
  - Index snapshot creation on export
  - Index diff computation (added, removed, changed, unchanged)
  - GET /index/imports/{id}/export-diff endpoint
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from backend.app.models.import_model import Import
from backend.app.models.index_artist_model import IndexArtist
from backend.app.models.index_cat_number_model import IndexCatNumber
from backend.app.models.export_snapshot_model import ExportSnapshot
from backend.app.services.export_diff_service import (
    save_index_export_snapshot,
    get_last_snapshot,
    compute_index_diff,
    _collect_index_export_data,
    _flatten_index_entries,
    _entry_key,
    _entry_display_name,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_index_import(db: Session, *, filename: str = "test.xlsx") -> Import:
    imp = Import(filename=filename, product_type="artists_index")
    db.add(imp)
    db.commit()
    db.refresh(imp)
    return imp


def _seed_artist(
    db: Session,
    imp: Import,
    *,
    first_name: str = "Jane",
    last_name: str = "Smith",
    quals: str | None = None,
    is_ra_member: bool = False,
    is_company: bool = False,
    row_number: int = 2,
    include_in_export: bool = True,
) -> IndexArtist:
    sort_key = f"{(last_name or '').lower()} {(first_name or '').lower()}".strip()
    artist = IndexArtist(
        import_id=imp.id,
        row_number=row_number,
        raw_first_name=first_name,
        raw_last_name=last_name,
        raw_quals=quals,
        first_name=first_name,
        last_name=last_name,
        quals=quals,
        is_ra_member=is_ra_member,
        is_company=is_company,
        sort_key=sort_key,
        include_in_export=include_in_export,
    )
    db.add(artist)
    db.commit()
    db.refresh(artist)
    return artist


def _seed_cat_no(
    db: Session,
    artist: IndexArtist,
    cat_no: int,
    *,
    courtesy: str | None = None,
) -> IndexCatNumber:
    cn = IndexCatNumber(
        artist_id=artist.id,
        cat_no=cat_no,
        source_row=artist.row_number,
        courtesy=courtesy,
    )
    db.add(cn)
    db.commit()
    db.refresh(cn)
    return cn


# ---------------------------------------------------------------------------
# Unit tests: _entry_key / _entry_display_name
# ---------------------------------------------------------------------------


class TestEntryKeyAndName:
    def test_entry_key_no_courtesy(self):
        e = {"sort_key": "smith jane", "courtesy": None}
        assert _entry_key(e) == "smith jane::"

    def test_entry_key_with_courtesy(self):
        e = {"sort_key": "smith jane", "courtesy": "Courtesy of X"}
        assert _entry_key(e) == "smith jane::Courtesy of X"

    def test_display_name_full(self):
        e = {"last_name": "Smith", "first_name": "Jane", "quals": "RA"}
        assert _entry_display_name(e) == "SMITH, Jane RA"

    def test_display_name_no_quals(self):
        e = {"last_name": "Adams", "first_name": "Roger", "quals": None}
        assert _entry_display_name(e) == "ADAMS, Roger"

    def test_display_name_missing(self):
        e = {"last_name": None, "first_name": None, "quals": None}
        assert _entry_display_name(e) == "(unknown)"


# ---------------------------------------------------------------------------
# Unit tests: _flatten_index_entries
# ---------------------------------------------------------------------------


class TestFlattenIndexEntries:
    def test_basic_flatten(self):
        data = [
            {"sort_key": "a", "courtesy": None, "first_name": "A"},
            {"sort_key": "b", "courtesy": None, "first_name": "B"},
        ]
        flat = _flatten_index_entries(data)
        assert len(flat) == 2
        assert "a::" in flat
        assert "b::" in flat

    def test_duplicate_keys_disambiguated(self):
        data = [
            {"sort_key": "a", "courtesy": None, "first_name": "A"},
            {"sort_key": "a", "courtesy": None, "first_name": "A2"},
        ]
        flat = _flatten_index_entries(data)
        assert len(flat) == 2


# ---------------------------------------------------------------------------
# Unit tests: save and retrieve snapshot
# ---------------------------------------------------------------------------


class TestSaveAndGetIndexSnapshot:
    def test_save_creates_snapshot(self, db_session):
        imp = _seed_index_import(db_session)
        artist = _seed_artist(db_session, imp)
        _seed_cat_no(db_session, artist, 101)

        snap = save_index_export_snapshot(imp.id, None, db_session)
        assert snap.id is not None
        assert snap.import_id == imp.id
        assert snap.template_id is None
        assert isinstance(snap.snapshot_data, list)
        assert len(snap.snapshot_data) == 1

    def test_get_last_snapshot_returns_most_recent(self, db_session):
        imp = _seed_index_import(db_session)
        artist = _seed_artist(db_session, imp)
        _seed_cat_no(db_session, artist, 101)

        snap1 = save_index_export_snapshot(imp.id, None, db_session)
        snap1.exported_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        db_session.commit()

        snap2 = save_index_export_snapshot(imp.id, None, db_session)
        snap2.exported_at = datetime(2025, 1, 2, tzinfo=timezone.utc)
        db_session.commit()

        latest = get_last_snapshot(imp.id, None, db_session)
        assert latest.id == snap2.id

    def test_snapshot_with_template_id(self, db_session):
        imp = _seed_index_import(db_session)
        artist = _seed_artist(db_session, imp)
        _seed_cat_no(db_session, artist, 101)
        tid = uuid.uuid4()

        save_index_export_snapshot(imp.id, tid, db_session)
        assert get_last_snapshot(imp.id, None, db_session) is None
        assert get_last_snapshot(imp.id, tid, db_session) is not None


# ---------------------------------------------------------------------------
# Unit tests: _collect_index_export_data
# ---------------------------------------------------------------------------


class TestCollectIndexExportData:
    def test_returns_serialised_entries(self, db_session):
        imp = _seed_index_import(db_session)
        a = _seed_artist(db_session, imp, first_name="Roger", last_name="Adams")
        _seed_cat_no(db_session, a, 101)

        data = _collect_index_export_data(imp.id, db_session)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["first_name"] == "Roger"
        assert data[0]["last_name"] == "Adams"
        assert data[0]["cat_nos"] == [101]

    def test_excluded_artists_omitted(self, db_session):
        imp = _seed_index_import(db_session)
        a1 = _seed_artist(db_session, imp, first_name="A", last_name="Included")
        _seed_cat_no(db_session, a1, 1)
        a2 = _seed_artist(
            db_session,
            imp,
            first_name="B",
            last_name="Excluded",
            include_in_export=False,
            row_number=3,
        )
        _seed_cat_no(db_session, a2, 2)

        data = _collect_index_export_data(imp.id, db_session)
        assert len(data) == 1
        assert data[0]["last_name"] == "Included"


# ---------------------------------------------------------------------------
# Unit tests: compute_index_diff
# ---------------------------------------------------------------------------


class TestComputeIndexDiff:
    def test_no_previous_export(self, db_session):
        imp = _seed_index_import(db_session)
        a = _seed_artist(db_session, imp)
        _seed_cat_no(db_session, a, 1)

        diff = compute_index_diff(imp.id, None, db_session)
        assert diff["has_changes"] is False
        assert diff["no_previous_export"] is True
        assert diff["added"] == []
        assert diff["removed"] == []

    def test_no_changes(self, db_session):
        imp = _seed_index_import(db_session)
        a = _seed_artist(db_session, imp)
        _seed_cat_no(db_session, a, 1)

        save_index_export_snapshot(imp.id, None, db_session)

        diff = compute_index_diff(imp.id, None, db_session)
        assert diff["has_changes"] is False
        assert diff["unchanged_count"] == 1

    def test_added_entry(self, db_session):
        imp = _seed_index_import(db_session)
        a1 = _seed_artist(db_session, imp)
        _seed_cat_no(db_session, a1, 1)

        save_index_export_snapshot(imp.id, None, db_session)

        # Add a new artist
        a2 = _seed_artist(
            db_session, imp, first_name="Bob", last_name="Brown", row_number=3
        )
        _seed_cat_no(db_session, a2, 2)

        diff = compute_index_diff(imp.id, None, db_session)
        assert diff["has_changes"] is True
        assert len(diff["added"]) == 1
        assert "BROWN" in diff["added"][0]["name"]
        assert diff["unchanged_count"] == 1

    def test_removed_entry(self, db_session):
        imp = _seed_index_import(db_session)
        a1 = _seed_artist(db_session, imp)
        _seed_cat_no(db_session, a1, 1)
        a2 = _seed_artist(
            db_session, imp, first_name="Bob", last_name="Brown", row_number=3
        )
        _seed_cat_no(db_session, a2, 2)

        save_index_export_snapshot(imp.id, None, db_session)

        # Exclude one artist
        a2.include_in_export = False
        db_session.commit()

        diff = compute_index_diff(imp.id, None, db_session)
        assert diff["has_changes"] is True
        assert len(diff["removed"]) == 1
        assert "BROWN" in diff["removed"][0]["name"]
        assert diff["unchanged_count"] == 1

    def test_changed_entry_field_level(self, db_session):
        imp = _seed_index_import(db_session)
        a = _seed_artist(db_session, imp, first_name="Jane", last_name="Smith")
        _seed_cat_no(db_session, a, 1)

        save_index_export_snapshot(imp.id, None, db_session)

        # Change the quals
        a.quals = "RA"
        db_session.commit()

        diff = compute_index_diff(imp.id, None, db_session)
        assert diff["has_changes"] is True
        assert len(diff["changed"]) == 1
        ch = diff["changed"][0]
        assert any(
            f["field"] == "quals" and f["old"] is None and f["new"] == "RA"
            for f in ch["fields"]
        )

    def test_cat_nos_change_detected(self, db_session):
        """Adding a cat number should appear as a field change on cat_nos."""
        imp = _seed_index_import(db_session)
        a = _seed_artist(db_session, imp)
        _seed_cat_no(db_session, a, 1)

        save_index_export_snapshot(imp.id, None, db_session)

        # Add another cat number
        _seed_cat_no(db_session, a, 5)

        diff = compute_index_diff(imp.id, None, db_session)
        assert diff["has_changes"] is True
        assert len(diff["changed"]) == 1
        cat_field = next(
            f for f in diff["changed"][0]["fields"] if f["field"] == "cat_nos"
        )
        assert cat_field["old"] == [1]
        assert sorted(cat_field["new"]) == [1, 5]

    def test_combined_added_removed_changed(self, db_session):
        imp = _seed_index_import(db_session)
        a_stay = _seed_artist(db_session, imp, first_name="Stay", last_name="Same")
        _seed_cat_no(db_session, a_stay, 1)
        a_change = _seed_artist(
            db_session, imp, first_name="Will", last_name="Change", row_number=3
        )
        _seed_cat_no(db_session, a_change, 2)
        a_remove = _seed_artist(
            db_session, imp, first_name="Goes", last_name="Away", row_number=4
        )
        _seed_cat_no(db_session, a_remove, 3)

        save_index_export_snapshot(imp.id, None, db_session)

        # Modify, exclude, add
        a_change.quals = "OBE"
        a_remove.include_in_export = False
        a_new = _seed_artist(
            db_session, imp, first_name="Brand", last_name="New", row_number=5
        )
        _seed_cat_no(db_session, a_new, 4)
        db_session.commit()

        diff = compute_index_diff(imp.id, None, db_session)
        assert diff["has_changes"] is True
        assert len(diff["added"]) == 1
        assert len(diff["removed"]) == 1
        assert len(diff["changed"]) == 1
        assert diff["unchanged_count"] == 1


# ---------------------------------------------------------------------------
# Route tests: GET /index/imports/{id}/export-diff
# ---------------------------------------------------------------------------


class TestIndexExportDiffRoute:
    def test_diff_no_previous_export(self, client, db_session):
        imp = _seed_index_import(db_session)
        a = _seed_artist(db_session, imp)
        _seed_cat_no(db_session, a, 1)

        r = client.get(f"/index/imports/{imp.id}/export-diff")
        assert r.status_code == 200
        data = r.json()
        assert data["has_changes"] is False
        assert data["no_previous_export"] is True

    def test_diff_after_export_no_changes(self, client, db_session):
        imp = _seed_index_import(db_session)
        a = _seed_artist(db_session, imp)
        _seed_cat_no(db_session, a, 101)

        # Trigger an export to create snapshot
        r = client.get(f"/index/imports/{imp.id}/export-tags")
        assert r.status_code == 200

        # Diff should show no changes
        r = client.get(f"/index/imports/{imp.id}/export-diff")
        assert r.status_code == 200
        data = r.json()
        assert data["has_changes"] is False
        assert data["unchanged_count"] == 1

    def test_diff_after_export_with_change(self, client, db_session):
        imp = _seed_index_import(db_session)
        a = _seed_artist(db_session, imp)
        _seed_cat_no(db_session, a, 101)

        # Export (creates snapshot)
        client.get(f"/index/imports/{imp.id}/export-tags")

        # Modify artist
        a.quals = "CBE"
        db_session.commit()

        r = client.get(f"/index/imports/{imp.id}/export-diff")
        assert r.status_code == 200
        data = r.json()
        assert data["has_changes"] is True
        assert len(data["changed"]) == 1
        assert any(
            f["field"] == "quals" and f["new"] == "CBE"
            for f in data["changed"][0]["fields"]
        )

    def test_snapshot_created_on_tags_export(self, client, db_session):
        imp = _seed_index_import(db_session)
        a = _seed_artist(db_session, imp)
        _seed_cat_no(db_session, a, 101)

        r = client.get(f"/index/imports/{imp.id}/export-tags")
        assert r.status_code == 200

        snap = get_last_snapshot(imp.id, None, db_session)
        assert snap is not None
        assert isinstance(snap.snapshot_data, list)

    def test_letter_export_does_not_snapshot(self, client, db_session):
        """Per-letter exports should NOT create a snapshot (partial export)."""
        imp = _seed_index_import(db_session)
        a = _seed_artist(db_session, imp, last_name="Smith")
        _seed_cat_no(db_session, a, 101)

        r = client.get(f"/index/imports/{imp.id}/export-tags?letter=S")
        assert r.status_code == 200

        snap = get_last_snapshot(imp.id, None, db_session)
        assert snap is None

    def test_404_for_nonexistent_import(self, client):
        fake_id = uuid.uuid4()
        r = client.get(f"/index/imports/{fake_id}/export-diff")
        assert r.status_code == 404
