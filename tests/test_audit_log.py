"""
Tests for audit log API endpoints:
  - GET /imports/{import_id}/audit-log
  - GET /audit-log (global)
"""

import uuid as _uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.db import Base
from backend.app.api.import_routes import router, get_db
from backend.app.models.import_model import Import
from backend.app.models.section_model import Section
from backend.app.models.work_model import Work
from backend.app.models.override_model import WorkOverride
from backend.app.models.audit_log_model import AuditLog
from backend.app.models.ruleset_model import Ruleset
from backend.app.models.index_artist_model import IndexArtist


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_session():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=eng)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=eng)
    session = Session()
    yield session
    session.close()
    eng.dispose()


@pytest.fixture()
def client(db_session):
    app = FastAPI()
    app.include_router(router)

    def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_import(db, filename="test.xlsx"):
    rec = Import(filename=filename)
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def _seed_section(db, imp, name="Section A", position=1):
    sec = Section(import_id=imp.id, name=name, position=position)
    db.add(sec)
    db.commit()
    db.refresh(sec)
    return sec


def _seed_work(
    db, imp, sec, position=1, raw_cat_no="1", title="Sunset", artist_name="Jane"
):
    w = Work(
        import_id=imp.id,
        section_id=sec.id,
        position_in_section=position,
        raw_cat_no=raw_cat_no,
        title=title,
        artist_name=artist_name,
        include_in_export=True,
    )
    db.add(w)
    db.commit()
    db.refresh(w)
    return w


def _seed_audit(
    db,
    imp,
    work=None,
    action="override_set",
    field="title_override",
    old_value=None,
    new_value="New Title",
):
    log = AuditLog(
        import_id=imp.id,
        work_id=work.id if work else None,
        action=action,
        field=field,
        old_value=old_value,
        new_value=new_value,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


# =========================================================================== #
# Per-import audit log
# =========================================================================== #


class TestImportAuditLog:
    def test_empty_audit_log(self, client, db_session):
        imp = _seed_import(db_session)
        r = client.get(f"/imports/{imp.id}/audit-log")
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_audit_entries(self, client, db_session):
        imp = _seed_import(db_session)
        sec = _seed_section(db_session, imp)
        work = _seed_work(db_session, imp, sec)
        _seed_audit(db_session, imp, work)
        _seed_audit(
            db_session, imp, work, field="price_numeric_override", new_value="1000"
        )

        r = client.get(f"/imports/{imp.id}/audit-log")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 2

    def test_includes_work_context(self, client, db_session):
        imp = _seed_import(db_session)
        sec = _seed_section(db_session, imp)
        work = _seed_work(
            db_session, imp, sec, raw_cat_no="42", title="Dawn", artist_name="Alice"
        )
        _seed_audit(db_session, imp, work)

        r = client.get(f"/imports/{imp.id}/audit-log")
        data = r.json()
        assert len(data) == 1
        entry = data[0]
        assert entry["cat_no"] == "42"
        assert entry["artist_name"] == "Alice"
        assert entry["title"] == "Dawn"
        assert entry["work_id"] == str(work.id)

    def test_import_level_entry(self, client, db_session):
        imp = _seed_import(db_session)
        _seed_audit(
            db_session,
            imp,
            work=None,
            action="reimport",
            field=None,
            new_value="matched=5, added=1",
        )

        r = client.get(f"/imports/{imp.id}/audit-log")
        data = r.json()
        assert len(data) == 1
        assert data[0]["action"] == "reimport"
        assert data[0]["work_id"] is None

    def test_newest_first(self, client, db_session):
        import datetime

        imp = _seed_import(db_session)
        sec = _seed_section(db_session, imp)
        work = _seed_work(db_session, imp, sec)
        # Use explicit timestamps to guarantee ordering
        log1 = AuditLog(
            import_id=imp.id,
            work_id=work.id,
            action="override_set",
            field="title_override",
            new_value="First",
            created_at=datetime.datetime(2026, 1, 1, 12, 0, 0),
        )
        log2 = AuditLog(
            import_id=imp.id,
            work_id=work.id,
            action="override_set",
            field="title_override",
            new_value="Second",
            created_at=datetime.datetime(2026, 1, 1, 12, 0, 1),
        )
        db_session.add_all([log1, log2])
        db_session.commit()

        r = client.get(f"/imports/{imp.id}/audit-log")
        data = r.json()
        # Second entry was created later, should appear first
        assert data[0]["new_value"] == "Second"
        assert data[1]["new_value"] == "First"

    def test_limit_parameter(self, client, db_session):
        imp = _seed_import(db_session)
        sec = _seed_section(db_session, imp)
        work = _seed_work(db_session, imp, sec)
        for i in range(10):
            _seed_audit(db_session, imp, work, new_value=f"Entry {i}")

        r = client.get(f"/imports/{imp.id}/audit-log?limit=3")
        assert r.status_code == 200
        assert len(r.json()) == 3

    def test_404_for_nonexistent_import(self, client):
        fake_id = str(_uuid.uuid4())
        r = client.get(f"/imports/{fake_id}/audit-log")
        assert r.status_code == 404

    def test_does_not_leak_other_import(self, client, db_session):
        imp1 = _seed_import(db_session, filename="a.xlsx")
        imp2 = _seed_import(db_session, filename="b.xlsx")
        sec1 = _seed_section(db_session, imp1)
        sec2 = _seed_section(db_session, imp2, name="Section B")
        work1 = _seed_work(db_session, imp1, sec1)
        work2 = _seed_work(db_session, imp2, sec2)
        _seed_audit(db_session, imp1, work1, new_value="Import 1")
        _seed_audit(db_session, imp2, work2, new_value="Import 2")

        r = client.get(f"/imports/{imp1.id}/audit-log")
        data = r.json()
        assert len(data) == 1
        assert data[0]["new_value"] == "Import 1"


# =========================================================================== #
# Global audit log
# =========================================================================== #


class TestGlobalAuditLog:
    def test_empty_global(self, client):
        r = client.get("/audit-log")
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_all_imports(self, client, db_session):
        imp1 = _seed_import(db_session, filename="a.xlsx")
        imp2 = _seed_import(db_session, filename="b.xlsx")
        sec1 = _seed_section(db_session, imp1)
        sec2 = _seed_section(db_session, imp2, name="Section B")
        work1 = _seed_work(db_session, imp1, sec1)
        work2 = _seed_work(db_session, imp2, sec2)
        _seed_audit(db_session, imp1, work1, new_value="From import 1")
        _seed_audit(db_session, imp2, work2, new_value="From import 2")

        r = client.get("/audit-log")
        data = r.json()
        assert len(data) == 2
        import_ids = {d["import_id"] for d in data}
        assert str(imp1.id) in import_ids
        assert str(imp2.id) in import_ids

    def test_global_limit(self, client, db_session):
        imp = _seed_import(db_session)
        sec = _seed_section(db_session, imp)
        work = _seed_work(db_session, imp, sec)
        for i in range(10):
            _seed_audit(db_session, imp, work, new_value=f"Entry {i}")

        r = client.get("/audit-log?limit=5")
        assert r.status_code == 200
        assert len(r.json()) == 5


# =========================================================================== #
# Integration: overrides create audit entries visible in the endpoint
# =========================================================================== #


class TestAuditIntegration:
    def test_override_creates_audit_entry(self, client, db_session):
        imp = _seed_import(db_session)
        sec = _seed_section(db_session, imp)
        work = _seed_work(db_session, imp, sec)

        # Set an override via the API
        client.put(
            f"/imports/{imp.id}/works/{work.id}/override",
            json={"title_override": "New Title"},
        )

        r = client.get(f"/imports/{imp.id}/audit-log")
        data = r.json()
        assert len(data) >= 1
        actions = [d["action"] for d in data]
        assert "override_set" in actions

    def test_exclude_creates_audit_entry(self, client, db_session):
        imp = _seed_import(db_session)
        sec = _seed_section(db_session, imp)
        work = _seed_work(db_session, imp, sec)

        client.patch(f"/imports/{imp.id}/works/{work.id}/exclude?exclude=true")

        r = client.get(f"/imports/{imp.id}/audit-log")
        data = r.json()
        assert len(data) >= 1
        actions = [d["action"] for d in data]
        assert "work_excluded" in actions


# =========================================================================== #
# Template audit logging
# =========================================================================== #

_TEMPLATE_BODY = {
    "name": "Test Template",
    "currency_symbol": "£",
    "section_style": "SectionTitle",
    "entry_style": "CatalogueEntry",
    "edition_prefix": "edition of",
    "edition_brackets": True,
    "cat_no_style": "CatNo",
    "artist_style": "ArtistName",
    "honorifics_style": "Honorifics",
    "honorifics_lowercase": False,
    "title_style": "WorkTitle",
    "price_style": "Price",
    "medium_style": "Medium",
    "artwork_style": "Artwork",
    "thousands_separator": ",",
    "decimal_places": 0,
    "leading_separator": "none",
    "trailing_separator": "none",
    "final_sep_from_last_component": False,
    "components": [
        {"field": "work_number", "separator_after": "tab"},
        {"field": "artist", "separator_after": "tab"},
        {"field": "title", "separator_after": "tab"},
        {"field": "price", "separator_after": "none"},
    ],
}


class TestTemplateAuditLog:
    """Verify that template CRUD operations create audit entries."""

    def test_create_template_logs(self, client, db_session):
        r = client.post("/templates", json=_TEMPLATE_BODY)
        assert r.status_code == 201
        tid = r.json()["id"]

        logs = (
            db_session.query(AuditLog)
            .filter(AuditLog.template_id == _uuid.UUID(tid))
            .all()
        )
        assert len(logs) == 1
        assert logs[0].action == "template_created"
        assert logs[0].new_value == "Test Template"
        assert logs[0].import_id is None

    def test_update_template_logs(self, client, db_session):
        r = client.post("/templates", json=_TEMPLATE_BODY)
        tid = r.json()["id"]

        updated = {**_TEMPLATE_BODY, "name": "Renamed"}
        client.put(f"/templates/{tid}", json=updated)

        logs = (
            db_session.query(AuditLog)
            .filter(
                AuditLog.template_id == _uuid.UUID(tid),
                AuditLog.action == "template_updated",
            )
            .all()
        )
        assert len(logs) == 1
        assert logs[0].old_value == "Test Template"
        assert logs[0].new_value == "Renamed"

    def test_delete_template_logs(self, client, db_session):
        r = client.post("/templates", json=_TEMPLATE_BODY)
        tid = r.json()["id"]

        client.delete(f"/templates/{tid}")

        logs = (
            db_session.query(AuditLog)
            .filter(
                AuditLog.template_id == _uuid.UUID(tid),
                AuditLog.action == "template_deleted",
            )
            .all()
        )
        assert len(logs) == 1
        assert logs[0].old_value == "Test Template"

    def test_duplicate_template_logs(self, client, db_session):
        r = client.post("/templates", json=_TEMPLATE_BODY)
        tid = r.json()["id"]

        dup = client.post(f"/templates/{tid}/duplicate")
        assert dup.status_code == 201
        new_tid = dup.json()["id"]

        logs = (
            db_session.query(AuditLog)
            .filter(
                AuditLog.template_id == _uuid.UUID(new_tid),
                AuditLog.action == "template_duplicated",
            )
            .all()
        )
        assert len(logs) == 1
        assert logs[0].old_value == "Test Template"
        assert logs[0].new_value == "Copy of Test Template"

    def test_template_events_in_global_log(self, client, db_session):
        """Template events appear in the global audit-log endpoint."""
        client.post("/templates", json=_TEMPLATE_BODY)

        r = client.get("/audit-log")
        data = r.json()
        assert len(data) >= 1
        tmpl_entries = [d for d in data if d["action"] == "template_created"]
        assert len(tmpl_entries) == 1
        assert tmpl_entries[0]["import_id"] is None
        assert tmpl_entries[0]["template_name"] == "Test Template"

    def test_template_name_enrichment(self, client, db_session):
        """Global audit log enriches template_name from the Ruleset row."""
        r = client.post("/templates", json=_TEMPLATE_BODY)
        tid = r.json()["id"]

        resp = client.get("/audit-log")
        data = resp.json()
        tmpl = [d for d in data if d["template_id"] == tid]
        assert len(tmpl) == 1
        assert tmpl[0]["template_name"] == "Test Template"


# =========================================================================== #
# Index artist audit log enrichment
# =========================================================================== #


def _seed_index_artist(db, imp, first_name="Jane", last_name="Smith", quals="RA"):
    artist = IndexArtist(
        import_id=imp.id,
        row_number=1,
        raw_first_name=first_name,
        raw_last_name=last_name,
        first_name=first_name,
        last_name=last_name,
        quals=quals,
        sort_key=f"{last_name}, {first_name}",
    )
    db.add(artist)
    db.commit()
    db.refresh(artist)
    return artist


def _seed_index_audit(
    db,
    imp,
    artist,
    action="override_set",
    field="display_name_override",
    old_value=None,
    new_value="SMITH, Jane",
):
    log = AuditLog(
        import_id=imp.id,
        artist_id=artist.id,
        action=action,
        field=field,
        old_value=old_value,
        new_value=new_value,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


class TestIndexAuditLog:
    def test_index_audit_includes_artist_id(self, client, db_session):
        """Index audit entries include artist_id in the response."""
        imp = _seed_import(db_session, filename="index.xlsx")
        imp.product_type = "artists_index"
        db_session.commit()
        artist = _seed_index_artist(db_session, imp)
        _seed_index_audit(db_session, imp, artist)

        r = client.get(f"/imports/{imp.id}/audit-log")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["artist_id"] == str(artist.id)

    def test_index_audit_enriches_artist_name(self, client, db_session):
        """Index audit entries include index_artist_name from IndexArtist."""
        imp = _seed_import(db_session)
        artist = _seed_index_artist(db_session, imp, "Alice", "Johnson", "HON RA")
        _seed_index_audit(db_session, imp, artist)

        r = client.get(f"/imports/{imp.id}/audit-log")
        data = r.json()
        assert data[0]["index_artist_name"] == "JOHNSON, Alice HON RA"

    def test_index_audit_no_work_fields(self, client, db_session):
        """Index audit entries have null work fields (cat_no, artist_name, title)."""
        imp = _seed_import(db_session)
        artist = _seed_index_artist(db_session, imp)
        _seed_index_audit(db_session, imp, artist)

        r = client.get(f"/imports/{imp.id}/audit-log")
        data = r.json()
        assert data[0]["cat_no"] is None
        assert data[0]["artist_name"] is None
        assert data[0]["title"] is None

    def test_index_audit_in_global_log(self, client, db_session):
        """Index audit entries appear in the global audit-log endpoint."""
        imp = _seed_import(db_session)
        artist = _seed_index_artist(db_session, imp, "Bob", "Brown", "RA")
        _seed_index_audit(
            db_session,
            imp,
            artist,
            action="index_artist_excluded",
            field="include_in_export",
            old_value="True",
            new_value="False",
        )

        r = client.get("/audit-log")
        data = r.json()
        idx_entries = [d for d in data if d["action"] == "index_artist_excluded"]
        assert len(idx_entries) == 1
        assert idx_entries[0]["index_artist_name"] == "BROWN, Bob RA"
        assert idx_entries[0]["artist_id"] == str(artist.id)

    def test_index_audit_deleted_artist(self, client, db_session):
        """When the artist is deleted, index_artist_name is null."""
        imp = _seed_import(db_session)
        artist = _seed_index_artist(db_session, imp)
        _seed_index_audit(db_session, imp, artist)
        # Delete the artist
        db_session.delete(artist)
        db_session.commit()

        r = client.get(f"/imports/{imp.id}/audit-log")
        data = r.json()
        # artist_id still present but enrichment returns null
        assert len(data) == 1
        assert data[0]["index_artist_name"] is None
