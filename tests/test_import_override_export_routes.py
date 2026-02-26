"""
Route-level tests for imports, overrides, exclude/include, and export endpoints.

These complement the existing test_routes.py (templates & config) and the
unit-level tests for rendering, normalisation, etc.
"""

import uuid as _uuid

import pytest
from sqlalchemy.orm import Session

from backend.app.models.import_model import Import
from backend.app.models.section_model import Section
from backend.app.models.work_model import Work
from backend.app.models.override_model import WorkOverride
from backend.app.models.validation_warning_model import ValidationWarning
from backend.app.models.audit_log_model import AuditLog


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
    db: Session, import_rec: Import, *, name: str = "Section A", position: int = 1
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
    price_numeric: float | None = 500.00,
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


def _seed_warning(
    db: Session,
    import_rec: Import,
    work: Work | None = None,
    *,
    warning_type: str = "missing_title",
    message: str = "Title is missing",
) -> ValidationWarning:
    vw = ValidationWarning(
        import_id=import_rec.id,
        work_id=work.id if work else None,
        warning_type=warning_type,
        message=message,
    )
    db.add(vw)
    db.commit()
    db.refresh(vw)
    return vw


# =========================================================================== #
# Import list / delete routes                                                 #
# =========================================================================== #


class TestListImports:
    def test_empty_list(self, client):
        r = client.get("/imports")
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_seeded_imports(self, client, db_session):
        _seed_import(db_session, filename="alpha.xlsx")
        _seed_import(db_session, filename="beta.xlsx")

        r = client.get("/imports")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 2
        filenames = {d["filename"] for d in data}
        assert filenames == {"alpha.xlsx", "beta.xlsx"}

    def test_import_includes_section_and_work_counts(self, client, db_session):
        imp = _seed_import(db_session)
        sec = _seed_section(db_session, imp)
        _seed_work(db_session, imp, sec)
        _seed_work(db_session, imp, sec, position=2, title="Dawn")

        r = client.get("/imports")
        data = r.json()
        assert len(data) == 1
        assert data[0]["sections"] == 1
        assert data[0]["works"] == 2
        assert data[0]["override_count"] == 0
        assert data[0]["last_override_at"] is None

    def test_import_override_count(self, client, db_session):
        imp = _seed_import(db_session)
        sec = _seed_section(db_session, imp)
        w = _seed_work(db_session, imp, sec)
        ovr = WorkOverride(work_id=w.id, title_override="New Title")
        db_session.add(ovr)
        db_session.commit()

        r = client.get("/imports")
        data = r.json()
        assert data[0]["override_count"] == 1
        assert data[0]["last_override_at"] is not None


class TestDeleteImport:
    def test_delete_existing(self, client, db_session):
        imp = _seed_import(db_session)
        r = client.delete(f"/imports/{imp.id}")
        assert r.status_code == 204

        # Verify it's gone
        r2 = client.get("/imports")
        assert r2.json() == []

    def test_delete_nonexistent_returns_404(self, client):
        r = client.delete(f"/imports/{_uuid.uuid4()}")
        assert r.status_code == 404


# =========================================================================== #
# Sections & works listing                                                    #
# =========================================================================== #


class TestListSections:
    def test_returns_sections_with_works(self, client, db_session):
        imp = _seed_import(db_session)
        sec = _seed_section(db_session, imp, name="Gallery I")
        _seed_work(db_session, imp, sec, title="Painting A")

        r = client.get(f"/imports/{imp.id}/sections")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["name"] == "Gallery I"
        assert len(data[0]["works"]) == 1
        assert data[0]["works"][0]["title"] == "Painting A"

    def test_empty_import_returns_empty_list(self, client, db_session):
        imp = _seed_import(db_session)
        r = client.get(f"/imports/{imp.id}/sections")
        assert r.status_code == 200
        assert r.json() == []

    def test_works_include_override_when_present(self, client, db_session):
        imp = _seed_import(db_session)
        sec = _seed_section(db_session, imp)
        w = _seed_work(db_session, imp, sec)
        ovr = WorkOverride(work_id=w.id, title_override="Overridden")
        db_session.add(ovr)
        db_session.commit()

        r = client.get(f"/imports/{imp.id}/sections")
        work_data = r.json()[0]["works"][0]
        assert work_data["override"] is not None
        assert work_data["override"]["title_override"] == "Overridden"

    def test_works_override_is_null_when_absent(self, client, db_session):
        imp = _seed_import(db_session)
        sec = _seed_section(db_session, imp)
        _seed_work(db_session, imp, sec)

        r = client.get(f"/imports/{imp.id}/sections")
        work_data = r.json()[0]["works"][0]
        assert work_data["override"] is None


# =========================================================================== #
# Preview                                                                     #
# =========================================================================== #


class TestPreview:
    def test_preview_basic(self, client, db_session):
        imp = _seed_import(db_session)
        sec = _seed_section(db_session, imp, name="Main Hall")
        _seed_work(
            db_session,
            imp,
            sec,
            title="Landscape",
            artist_name="Alice",
            price_text="£1,000",
            raw_cat_no="42",
        )

        r = client.get(f"/imports/{imp.id}/preview")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["name"] == "Main Hall"
        work = data[0]["works"][0]
        assert work["title"] == "Landscape"
        assert work["artist"] == "Alice"
        assert work["number"] == "42"

    def test_preview_edition_display(self, client, db_session):
        imp = _seed_import(db_session)
        sec = _seed_section(db_session, imp)
        _seed_work(
            db_session,
            imp,
            sec,
            edition_total=50,
            edition_price_numeric=200.0,
        )

        r = client.get(f"/imports/{imp.id}/preview")
        work = r.json()[0]["works"][0]
        assert "edition of 50" in work["edition_display"]
        assert "200" in work["edition_display"]

    def test_preview_edition_without_price(self, client, db_session):
        imp = _seed_import(db_session)
        sec = _seed_section(db_session, imp)
        _seed_work(db_session, imp, sec, edition_total=25)

        r = client.get(f"/imports/{imp.id}/preview")
        work = r.json()[0]["works"][0]
        assert work["edition_display"] == "(edition of 25)"

    def test_preview_no_edition(self, client, db_session):
        imp = _seed_import(db_session)
        sec = _seed_section(db_session, imp)
        _seed_work(db_session, imp, sec)

        r = client.get(f"/imports/{imp.id}/preview")
        work = r.json()[0]["works"][0]
        assert work["edition_display"] is None


# =========================================================================== #
# Warnings                                                                    #
# =========================================================================== #


class TestWarnings:
    def test_returns_warnings(self, client, db_session):
        imp = _seed_import(db_session)
        sec = _seed_section(db_session, imp)
        w = _seed_work(db_session, imp, sec, title="Untitled")
        _seed_warning(
            db_session, imp, w, warning_type="missing_title", message="No title"
        )

        r = client.get(f"/imports/{imp.id}/warnings")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["warning_type"] == "missing_title"
        assert data[0]["artist_name"] == "Jane Doe"  # from the seeded work

    def test_empty_warnings(self, client, db_session):
        imp = _seed_import(db_session)
        r = client.get(f"/imports/{imp.id}/warnings")
        assert r.status_code == 200
        assert r.json() == []

    def test_import_level_warning_has_null_work_fields(self, client, db_session):
        imp = _seed_import(db_session)
        _seed_warning(
            db_session, imp, None, warning_type="duplicate_filename", message="Dup"
        )

        r = client.get(f"/imports/{imp.id}/warnings")
        data = r.json()
        assert len(data) == 1
        assert data[0]["work_id"] is None
        assert data[0]["artist_name"] is None


# =========================================================================== #
# Override CRUD                                                               #
# =========================================================================== #


class TestOverrideCRUD:
    def _make_work(self, db_session):
        imp = _seed_import(db_session)
        sec = _seed_section(db_session, imp)
        w = _seed_work(db_session, imp, sec)
        return imp, w

    # --- GET override ---
    def test_get_override_404_when_none_exists(self, client, db_session):
        imp, w = self._make_work(db_session)
        r = client.get(f"/imports/{imp.id}/works/{w.id}/override")
        assert r.status_code == 404

    def test_get_override_returns_existing(self, client, db_session):
        imp, w = self._make_work(db_session)
        ovr = WorkOverride(work_id=w.id, title_override="New")
        db_session.add(ovr)
        db_session.commit()

        r = client.get(f"/imports/{imp.id}/works/{w.id}/override")
        assert r.status_code == 200
        assert r.json()["title_override"] == "New"

    def test_get_override_404_wrong_import(self, client, db_session):
        imp, w = self._make_work(db_session)
        fake_import = _uuid.uuid4()
        r = client.get(f"/imports/{fake_import}/works/{w.id}/override")
        assert r.status_code == 404

    # --- PUT override (create) ---
    def test_put_creates_override(self, client, db_session):
        imp, w = self._make_work(db_session)
        r = client.put(
            f"/imports/{imp.id}/works/{w.id}/override",
            json={"title_override": "Overridden Title"},
        )
        assert r.status_code == 200
        assert r.json()["title_override"] == "Overridden Title"
        assert r.json()["work_id"] == str(w.id)

    def test_put_creates_audit_log(self, client, db_session):
        imp, w = self._make_work(db_session)
        client.put(
            f"/imports/{imp.id}/works/{w.id}/override",
            json={"title_override": "Logged"},
        )
        logs = db_session.query(AuditLog).filter(AuditLog.work_id == w.id).all()
        assert len(logs) >= 1
        assert any(
            l.action == "override_set" and l.field == "title_override" for l in logs
        )

    # --- PUT override (update) ---
    def test_put_updates_existing_override(self, client, db_session):
        imp, w = self._make_work(db_session)
        client.put(
            f"/imports/{imp.id}/works/{w.id}/override",
            json={"title_override": "First"},
        )
        r2 = client.put(
            f"/imports/{imp.id}/works/{w.id}/override",
            json={"title_override": "Second"},
        )
        assert r2.status_code == 200
        assert r2.json()["title_override"] == "Second"

    def test_put_partial_fields(self, client, db_session):
        imp, w = self._make_work(db_session)
        r = client.put(
            f"/imports/{imp.id}/works/{w.id}/override",
            json={"artist_name_override": "Bob", "medium_override": "Oil on canvas"},
        )
        assert r.status_code == 200
        assert r.json()["artist_name_override"] == "Bob"
        assert r.json()["medium_override"] == "Oil on canvas"
        assert r.json()["title_override"] is None
        assert r.json()["notes"] is None

    def test_put_notes_roundtrip(self, client, db_session):
        imp, w = self._make_work(db_session)
        r = client.put(
            f"/imports/{imp.id}/works/{w.id}/override",
            json={"notes": "Editorial note"},
        )
        assert r.status_code == 200
        assert r.json()["notes"] == "Editorial note"
        # GET should also return the note
        r2 = client.get(f"/imports/{imp.id}/works/{w.id}/override")
        assert r2.json()["notes"] == "Editorial note"

    # --- DELETE override ---
    def test_delete_override(self, client, db_session):
        imp, w = self._make_work(db_session)
        client.put(
            f"/imports/{imp.id}/works/{w.id}/override",
            json={"title_override": "Temp"},
        )
        r = client.delete(f"/imports/{imp.id}/works/{w.id}/override")
        assert r.status_code == 204

        # Confirm it's gone
        r2 = client.get(f"/imports/{imp.id}/works/{w.id}/override")
        assert r2.status_code == 404

    def test_delete_override_404_when_none(self, client, db_session):
        imp, w = self._make_work(db_session)
        r = client.delete(f"/imports/{imp.id}/works/{w.id}/override")
        assert r.status_code == 404

    def test_delete_override_creates_audit_log(self, client, db_session):
        imp, w = self._make_work(db_session)
        client.put(
            f"/imports/{imp.id}/works/{w.id}/override",
            json={"title_override": "Temp"},
        )
        client.delete(f"/imports/{imp.id}/works/{w.id}/override")
        logs = (
            db_session.query(AuditLog)
            .filter(AuditLog.action == "override_deleted")
            .all()
        )
        assert len(logs) == 1


# =========================================================================== #
# Exclude / include toggle                                                    #
# =========================================================================== #


class TestExcludeInclude:
    def _make_work(self, db_session):
        imp = _seed_import(db_session)
        sec = _seed_section(db_session, imp)
        w = _seed_work(db_session, imp, sec)
        return imp, w

    def test_exclude_work(self, client, db_session):
        imp, w = self._make_work(db_session)
        r = client.patch(
            f"/imports/{imp.id}/works/{w.id}/exclude",
            params={"exclude": True},
        )
        assert r.status_code == 200
        assert r.json()["include_in_export"] is False

    def test_reinclude_work(self, client, db_session):
        imp, w = self._make_work(db_session)
        client.patch(
            f"/imports/{imp.id}/works/{w.id}/exclude",
            params={"exclude": True},
        )
        r = client.patch(
            f"/imports/{imp.id}/works/{w.id}/exclude",
            params={"exclude": False},
        )
        assert r.status_code == 200
        assert r.json()["include_in_export"] is True

    def test_exclude_creates_audit_log(self, client, db_session):
        imp, w = self._make_work(db_session)
        client.patch(
            f"/imports/{imp.id}/works/{w.id}/exclude",
            params={"exclude": True},
        )
        logs = (
            db_session.query(AuditLog).filter(AuditLog.action == "work_excluded").all()
        )
        assert len(logs) == 1

    def test_noop_exclude_does_not_create_audit_log(self, client, db_session):
        imp, w = self._make_work(db_session)
        # Work starts included, so exclude=False is a no-op
        client.patch(
            f"/imports/{imp.id}/works/{w.id}/exclude",
            params={"exclude": False},
        )
        logs = db_session.query(AuditLog).filter(AuditLog.work_id == w.id).all()
        assert len(logs) == 0

    def test_exclude_404_bad_work(self, client, db_session):
        imp = _seed_import(db_session)
        r = client.patch(
            f"/imports/{imp.id}/works/{_uuid.uuid4()}/exclude",
            params={"exclude": True},
        )
        assert r.status_code == 404


# =========================================================================== #
# Export routes (tagged text, JSON, XML, CSV)                                 #
# =========================================================================== #


class TestExportRoutes:
    def _seed_data(self, db_session):
        imp = _seed_import(db_session)
        sec = _seed_section(db_session, imp, name="Gallery I")
        _seed_work(
            db_session,
            imp,
            sec,
            title="Sunset",
            artist_name="Jane Doe",
            price_numeric=500.0,
            price_text="£500",
            raw_cat_no="1",
        )
        return imp, sec

    def test_export_json(self, client, db_session):
        imp, _ = self._seed_data(db_session)
        r = client.get(f"/imports/{imp.id}/export-json")
        assert r.status_code == 200
        data = r.json()
        assert "sections" in data
        assert len(data["sections"]) >= 1
        assert data["sections"][0]["section_name"] == "Gallery I"

    def test_export_xml(self, client, db_session):
        imp, _ = self._seed_data(db_session)
        r = client.get(f"/imports/{imp.id}/export-xml")
        assert r.status_code == 200
        assert b"<catalogue>" in r.content or b"<section" in r.content

    def test_export_csv(self, client, db_session):
        imp, _ = self._seed_data(db_session)
        r = client.get(f"/imports/{imp.id}/export-csv")
        assert r.status_code == 200
        text = r.text
        assert "section" in text.lower() or "title" in text.lower()
        lines = text.strip().split("\n")
        assert len(lines) >= 2  # header + at least one data row

    def test_export_tags_full(self, client, db_session):
        imp, _ = self._seed_data(db_session)
        r = client.get(f"/imports/{imp.id}/export-tags")
        assert r.status_code == 200
        # InDesign Tagged Text starts with a version header
        text = r.content.decode("mac_roman")
        assert "<ASCII-MAC>" in text

    def test_export_tags_single_section(self, client, db_session):
        imp, sec = self._seed_data(db_session)
        r = client.get(f"/imports/{imp.id}/sections/{sec.id}/export-tags")
        assert r.status_code == 200
        text = r.content.decode("mac_roman")
        assert "<ASCII-MAC>" in text

    def test_export_json_empty_import(self, client, db_session):
        imp = _seed_import(db_session)
        r = client.get(f"/imports/{imp.id}/export-json")
        assert r.status_code == 200
        assert r.json() == {"sections": []}

    def test_export_csv_empty_import(self, client, db_session):
        imp = _seed_import(db_session)
        r = client.get(f"/imports/{imp.id}/export-csv")
        assert r.status_code == 200
        # Should have at least a header row
        lines = r.text.strip().split("\n")
        assert len(lines) >= 1
