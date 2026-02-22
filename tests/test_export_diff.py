"""
Tests for the export diff / snapshot feature.

Covers:
  - ExportSnapshot creation on export
  - Diff computation (added, removed, changed, unchanged)
  - GET /imports/{id}/export-diff endpoint
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from backend.app.models.import_model import Import
from backend.app.models.section_model import Section
from backend.app.models.work_model import Work
from backend.app.models.export_snapshot_model import ExportSnapshot
from backend.app.services.export_diff_service import (
    save_export_snapshot,
    get_last_snapshot,
    compute_diff,
    _flatten_works,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_import(db: Session, *, filename: str = "test.xlsx") -> Import:
    rec = Import(filename=filename)
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def _seed_section(
    db: Session,
    import_rec: Import,
    *,
    name: str = "Section A",
    position: int = 1,
) -> Section:
    sec = Section(import_id=import_rec.id, name=name, position=position)
    db.add(sec)
    db.commit()
    db.refresh(sec)
    return sec


def _seed_work(
    db: Session,
    import_rec: Import,
    section: Section,
    *,
    position: int = 1,
    title: str = "Sunset",
    artist_name: str = "Jane Doe",
    price_numeric: float | None = 500.0,
    price_text: str | None = "£500",
    raw_cat_no: str | None = "1",
    edition_total: int | None = None,
    edition_price_numeric: float | None = None,
    medium: str | None = None,
    artwork: int | None = None,
) -> Work:
    w = Work(
        import_id=import_rec.id,
        section_id=section.id,
        position_in_section=position,
        raw_cat_no=raw_cat_no,
        title=title,
        artist_name=artist_name,
        price_numeric=price_numeric,
        price_text=price_text,
        edition_total=edition_total,
        edition_price_numeric=edition_price_numeric,
        medium=medium,
        artwork=artwork,
        include_in_export=True,
    )
    db.add(w)
    db.commit()
    db.refresh(w)
    return w


# ---------------------------------------------------------------------------
# Unit tests: save / retrieve snapshot
# ---------------------------------------------------------------------------


class TestSaveAndGetSnapshot:
    def test_save_creates_snapshot(self, db_session):
        imp = _seed_import(db_session)
        sec = _seed_section(db_session, imp)
        _seed_work(db_session, imp, sec)

        snap = save_export_snapshot(imp.id, None, db_session)
        assert snap.id is not None
        assert snap.import_id == imp.id
        assert snap.template_id is None
        assert isinstance(snap.snapshot_data, list)
        assert len(snap.snapshot_data) == 1  # one section

    def test_get_last_snapshot_returns_most_recent(self, db_session):
        imp = _seed_import(db_session)
        sec = _seed_section(db_session, imp)
        _seed_work(db_session, imp, sec)

        snap1 = save_export_snapshot(imp.id, None, db_session)
        # Force distinct timestamps (SQLite has sub-second precision issues)
        snap1.exported_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        db_session.commit()

        snap2 = save_export_snapshot(imp.id, None, db_session)
        snap2.exported_at = datetime(2025, 1, 2, tzinfo=timezone.utc)
        db_session.commit()

        latest = get_last_snapshot(imp.id, None, db_session)
        assert latest.id == snap2.id

    def test_get_last_snapshot_none_when_empty(self, db_session):
        imp = _seed_import(db_session)
        assert get_last_snapshot(imp.id, None, db_session) is None

    def test_snapshot_with_template_id(self, db_session):
        imp = _seed_import(db_session)
        sec = _seed_section(db_session, imp)
        _seed_work(db_session, imp, sec)
        tid = uuid.uuid4()

        save_export_snapshot(imp.id, tid, db_session)
        # Should not appear for None template
        assert get_last_snapshot(imp.id, None, db_session) is None
        # Should appear for matching template
        assert get_last_snapshot(imp.id, tid, db_session) is not None


# ---------------------------------------------------------------------------
# Unit tests: _flatten_works
# ---------------------------------------------------------------------------


class TestFlattenWorks:
    def test_basic_flatten(self):
        data = [
            {
                "section_name": "Gallery",
                "position": 1,
                "works": [
                    {"number": "1", "artist": "Alice", "title": "A"},
                    {"number": "2", "artist": "Bob", "title": "B"},
                ],
            }
        ]
        flat = _flatten_works(data)
        assert set(flat.keys()) == {"1", "2"}
        assert flat["1"]["artist"] == "Alice"
        assert flat["1"]["_section"] == "Gallery"

    def test_unnamed_works_get_synthetic_keys(self):
        data = [
            {
                "section_name": "S",
                "position": 1,
                "works": [
                    {"number": None, "artist": "X"},
                    {"number": None, "artist": "Y"},
                ],
            }
        ]
        flat = _flatten_works(data)
        assert len(flat) == 2
        keys = list(flat.keys())
        assert all(k.startswith("__unnamed_") for k in keys)

    def test_duplicate_numbers_disambiguated(self):
        data = [
            {
                "section_name": "S1",
                "position": 1,
                "works": [{"number": "5", "artist": "A"}],
            },
            {
                "section_name": "S2",
                "position": 2,
                "works": [{"number": "5", "artist": "B"}],
            },
        ]
        flat = _flatten_works(data)
        assert len(flat) == 2  # both present, disambiguated


# ---------------------------------------------------------------------------
# Unit tests: compute_diff
# ---------------------------------------------------------------------------


class TestComputeDiff:
    def test_no_previous_export_all_added(self, db_session):
        imp = _seed_import(db_session)
        sec = _seed_section(db_session, imp)
        _seed_work(db_session, imp, sec, raw_cat_no="1")
        _seed_work(db_session, imp, sec, raw_cat_no="2", position=2, title="Dawn")

        diff = compute_diff(imp.id, None, db_session)
        assert diff["has_changes"] is True
        assert diff["previous_exported_at"] is None
        assert len(diff["added"]) == 2
        assert diff["removed"] == []
        assert diff["changed"] == []
        assert diff["unchanged_count"] == 0

    def test_no_changes(self, db_session):
        imp = _seed_import(db_session)
        sec = _seed_section(db_session, imp)
        _seed_work(db_session, imp, sec, raw_cat_no="1")

        # Snapshot current state
        save_export_snapshot(imp.id, None, db_session)

        # Compute diff — nothing changed
        diff = compute_diff(imp.id, None, db_session)
        assert diff["has_changes"] is False
        assert diff["previous_exported_at"] is not None
        assert diff["added"] == []
        assert diff["removed"] == []
        assert diff["changed"] == []
        assert diff["unchanged_count"] == 1

    def test_added_work(self, db_session):
        imp = _seed_import(db_session)
        sec = _seed_section(db_session, imp)
        _seed_work(db_session, imp, sec, raw_cat_no="1")

        save_export_snapshot(imp.id, None, db_session)

        # Add a new work
        _seed_work(db_session, imp, sec, raw_cat_no="2", position=2, title="New Work")

        diff = compute_diff(imp.id, None, db_session)
        assert diff["has_changes"] is True
        assert len(diff["added"]) == 1
        assert diff["added"][0]["cat_no"] == "2"
        assert diff["unchanged_count"] == 1

    def test_removed_work(self, db_session):
        imp = _seed_import(db_session)
        sec = _seed_section(db_session, imp)
        w1 = _seed_work(db_session, imp, sec, raw_cat_no="1")
        w2 = _seed_work(db_session, imp, sec, raw_cat_no="2", position=2)

        save_export_snapshot(imp.id, None, db_session)

        # Delete one work
        db_session.delete(w2)
        db_session.commit()

        diff = compute_diff(imp.id, None, db_session)
        assert diff["has_changes"] is True
        assert len(diff["removed"]) == 1
        assert diff["removed"][0]["cat_no"] == "2"
        assert diff["unchanged_count"] == 1

    def test_changed_work_field_level(self, db_session):
        imp = _seed_import(db_session)
        sec = _seed_section(db_session, imp)
        w = _seed_work(
            db_session, imp, sec, raw_cat_no="10", title="Old Title", artist_name="Ann"
        )

        save_export_snapshot(imp.id, None, db_session)

        # Modify the work
        w.title = "New Title"
        db_session.commit()

        diff = compute_diff(imp.id, None, db_session)
        assert diff["has_changes"] is True
        assert len(diff["changed"]) == 1
        ch = diff["changed"][0]
        assert ch["cat_no"] == "10"
        assert any(
            f["field"] == "title"
            and f["old"] == "Old Title"
            and f["new"] == "New Title"
            for f in ch["fields"]
        )

    def test_combined_added_removed_changed(self, db_session):
        imp = _seed_import(db_session)
        sec = _seed_section(db_session, imp)
        w_stay = _seed_work(db_session, imp, sec, raw_cat_no="1", title="Stays Same")
        w_change = _seed_work(
            db_session, imp, sec, raw_cat_no="2", position=2, title="Will Change"
        )
        w_remove = _seed_work(
            db_session, imp, sec, raw_cat_no="3", position=3, title="Goes Away"
        )

        save_export_snapshot(imp.id, None, db_session)

        # Modify, remove, add
        w_change.title = "Changed!"
        db_session.delete(w_remove)
        _seed_work(db_session, imp, sec, raw_cat_no="4", position=4, title="Brand New")
        db_session.commit()

        diff = compute_diff(imp.id, None, db_session)
        assert diff["has_changes"] is True
        assert len(diff["added"]) == 1
        assert len(diff["removed"]) == 1
        assert len(diff["changed"]) == 1
        assert diff["unchanged_count"] == 1

    def test_section_change_detected(self, db_session):
        imp = _seed_import(db_session)
        sec_a = _seed_section(db_session, imp, name="Room A", position=1)
        sec_b = _seed_section(db_session, imp, name="Room B", position=2)
        w = _seed_work(db_session, imp, sec_a, raw_cat_no="5")

        save_export_snapshot(imp.id, None, db_session)

        # Move work to different section
        w.section_id = sec_b.id
        db_session.commit()

        diff = compute_diff(imp.id, None, db_session)
        assert diff["has_changes"] is True
        changed = diff["changed"]
        assert len(changed) == 1
        fields = {f["field"] for f in changed[0]["fields"]}
        assert "section" in fields


# ---------------------------------------------------------------------------
# Route tests: GET /imports/{id}/export-diff
# ---------------------------------------------------------------------------


class TestExportDiffRoute:
    def test_diff_no_previous_export(self, client, db_session):
        imp = _seed_import(db_session)
        sec = _seed_section(db_session, imp)
        _seed_work(db_session, imp, sec, raw_cat_no="1")

        r = client.get(f"/imports/{imp.id}/export-diff")
        assert r.status_code == 200
        data = r.json()
        assert data["has_changes"] is True
        assert data["previous_exported_at"] is None
        assert len(data["added"]) == 1

    def test_diff_after_export_no_changes(self, client, db_session):
        imp = _seed_import(db_session)
        sec = _seed_section(db_session, imp)
        _seed_work(db_session, imp, sec, raw_cat_no="1")

        # Trigger an export to create snapshot
        r = client.get(f"/imports/{imp.id}/export-json")
        assert r.status_code == 200

        # Diff should show no changes
        r = client.get(f"/imports/{imp.id}/export-diff")
        assert r.status_code == 200
        data = r.json()
        assert data["has_changes"] is False
        assert data["unchanged_count"] == 1

    def test_diff_after_export_with_change(self, client, db_session):
        imp = _seed_import(db_session)
        sec = _seed_section(db_session, imp)
        w = _seed_work(db_session, imp, sec, raw_cat_no="1", title="Before")

        # Export (snapshot)
        client.get(f"/imports/{imp.id}/export-json")

        # Modify work
        w.title = "After"
        db_session.commit()

        r = client.get(f"/imports/{imp.id}/export-diff")
        assert r.status_code == 200
        data = r.json()
        assert data["has_changes"] is True
        assert len(data["changed"]) == 1
        assert any(
            f["field"] == "title" and f["old"] == "Before" and f["new"] == "After"
            for f in data["changed"][0]["fields"]
        )

    def test_snapshot_created_on_tags_export(self, client, db_session):
        imp = _seed_import(db_session)
        sec = _seed_section(db_session, imp)
        _seed_work(db_session, imp, sec, raw_cat_no="1")

        # Export as tags
        r = client.get(f"/imports/{imp.id}/export-tags")
        assert r.status_code == 200

        # Snapshot should exist
        snap = get_last_snapshot(imp.id, None, db_session)
        assert snap is not None
        assert isinstance(snap.snapshot_data, list)

    def test_snapshot_created_on_csv_export(self, client, db_session):
        imp = _seed_import(db_session)
        sec = _seed_section(db_session, imp)
        _seed_work(db_session, imp, sec, raw_cat_no="1")

        r = client.get(f"/imports/{imp.id}/export-csv")
        assert r.status_code == 200

        snap = get_last_snapshot(imp.id, None, db_session)
        assert snap is not None

    def test_snapshot_created_on_xml_export(self, client, db_session):
        imp = _seed_import(db_session)
        sec = _seed_section(db_session, imp)
        _seed_work(db_session, imp, sec, raw_cat_no="1")

        r = client.get(f"/imports/{imp.id}/export-xml")
        assert r.status_code == 200

        snap = get_last_snapshot(imp.id, None, db_session)
        assert snap is not None
