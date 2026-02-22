"""
Tests for the re-import feature: PUT /imports/{import_id}/reimport

Covers:
  - Basic re-import replaces works and sections
  - Overrides preserved when cat_no matches
  - include_in_export preserved when cat_no matches
  - New works added, old works removed
  - Stats returned correctly (matched, added, removed, overrides_preserved)
  - Audit log entry created
  - Validation warnings regenerated
  - 404 when import does not exist
  - 400 when uploaded file is invalid
  - Duplicate cat_no in new spreadsheet (only first gets override)
  - Works without cat_no treated as new
"""

import io
import uuid as _uuid

import pytest
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.db import Base
from backend.app.api.import_routes import router, get_db
from backend.app.models.import_model import Import
from backend.app.models.section_model import Section
from backend.app.models.work_model import Work
from backend.app.models.override_model import WorkOverride
from backend.app.models.validation_warning_model import ValidationWarning
from backend.app.models.audit_log_model import AuditLog


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

ALL_HEADERS = [
    "Cat No",
    "Gallery",
    "Title",
    "Artist",
    "Price",
    "Edition",
    "Artwork",
    "Medium",
]


def _make_xlsx(headers: list[str], rows: list[list] | None = None) -> io.BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows or []:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _do_import(client, headers=None, rows=None) -> str:
    """Import a spreadsheet and return the import_id."""
    hdrs = headers or ALL_HEADERS
    data = rows or [
        [1, "Gallery A", "Sunset", "Jane Doe", "500", None, None, "Oil"],
        [2, "Gallery A", "Dawn", "John Smith RA", "1000", None, None, "Acrylic"],
        [3, "Gallery B", "Noon", "Alice", "NFS", None, None, None],
    ]
    buf = _make_xlsx(hdrs, data)
    r = client.post(
        "/import",
        files={
            "file": (
                "test.xlsx",
                buf,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["import_id"]


def _do_reimport(
    client, import_id: str, headers=None, rows=None, filename="updated.xlsx"
):
    """Re-import into an existing import and return the response."""
    hdrs = headers or ALL_HEADERS
    data = rows or [
        [1, "Gallery A", "Sunset UPDATED", "Jane Doe", "600", None, None, "Oil"],
        [2, "Gallery A", "Dawn", "John Smith RA", "1200", None, None, "Acrylic"],
        [4, "Gallery A", "New Work", "Bob", "300", None, None, "Pastel"],
    ]
    buf = _make_xlsx(hdrs, data)
    return client.put(
        f"/imports/{import_id}/reimport",
        files={
            "file": (
                filename,
                buf,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )


def _set_override(client, import_id: str, work_id: str, **fields):
    return client.put(f"/imports/{import_id}/works/{work_id}/override", json=fields)


def _get_sections(client, import_id: str):
    r = client.get(f"/imports/{import_id}/sections")
    assert r.status_code == 200
    return r.json()


# =========================================================================== #
# Tests
# =========================================================================== #


class TestReimportBasic:
    """Core re-import behaviour."""

    def test_reimport_replaces_works(self, client):
        import_id = _do_import(client)
        sections_before = _get_sections(client, import_id)
        total_before = sum(len(s["works"]) for s in sections_before)
        assert total_before == 3

        r = _do_reimport(client, import_id)
        assert r.status_code == 200
        data = r.json()
        assert data["import_id"] == import_id

        # After reimport with different works, data should reflect new spreadsheet
        sections_after = _get_sections(client, import_id)
        total_after = sum(len(s["works"]) for s in sections_after)
        assert total_after == 3  # 3 rows in the new spreadsheet

    def test_reimport_updates_work_data(self, client):
        import_id = _do_import(client)

        # Reimport with updated title for cat_no 1
        _do_reimport(client, import_id)

        sections = _get_sections(client, import_id)
        all_works = [w for s in sections for w in s["works"]]
        cat1 = next(w for w in all_works if w["raw_cat_no"] == "1")
        assert cat1["title"] == "Sunset UPDATED"
        assert cat1["price_numeric"] == 600.0

    def test_reimport_returns_correct_stats(self, client):
        import_id = _do_import(client)
        # Original: cat_no 1, 2, 3
        # Reimport: cat_no 1, 2, 4 → matched=2/added=1/removed=1

        r = _do_reimport(client, import_id)
        data = r.json()
        assert data["matched"] == 2
        assert data["added"] == 1
        assert data["removed"] == 1

    def test_reimport_updates_filename(self, client):
        import_id = _do_import(client)
        r = _do_reimport(client, import_id, filename="v2-catalogue.xlsx")
        assert r.status_code == 200

        imports = client.get("/imports").json()
        imp = next(i for i in imports if i["id"] == import_id)
        assert imp["filename"] == "v2-catalogue.xlsx"

    def test_reimport_sections_restructured(self, client):
        import_id = _do_import(client)
        # Original has Gallery A and Gallery B
        sections_before = _get_sections(client, import_id)
        names_before = {s["name"] for s in sections_before}
        assert "Gallery A" in names_before
        assert "Gallery B" in names_before

        # Reimport with only Gallery A (no Gallery B)
        r = _do_reimport(client, import_id)
        assert r.status_code == 200

        sections_after = _get_sections(client, import_id)
        names_after = {s["name"] for s in sections_after}
        assert "Gallery A" in names_after
        assert "Gallery B" not in names_after


class TestReimportOverridePreservation:
    """Override and include_in_export preservation."""

    def test_override_preserved_by_cat_no(self, client):
        import_id = _do_import(client)
        sections = _get_sections(client, import_id)
        all_works = [w for s in sections for w in s["works"]]
        work1 = next(w for w in all_works if w["raw_cat_no"] == "1")

        # Set an override on cat_no 1
        _set_override(
            client,
            import_id,
            work1["id"],
            title_override="Custom Title",
            price_numeric_override=999.0,
        )

        # Reimport — cat_no 1 still exists
        r = _do_reimport(client, import_id)
        data = r.json()
        assert (
            data["overrides_preserved"] == 1
        )  # only cat_no 1 had an override (2 matched but only 1 has override)

        # Verify override is still there
        sections = _get_sections(client, import_id)
        all_works = [w for s in sections for w in s["works"]]
        work1_new = next(w for w in all_works if w["raw_cat_no"] == "1")
        assert work1_new["override"] is not None
        assert work1_new["override"]["title_override"] == "Custom Title"
        assert work1_new["override"]["price_numeric_override"] == 999.0

    def test_override_multiple_fields_preserved(self, client):
        import_id = _do_import(client)
        sections = _get_sections(client, import_id)
        all_works = [w for s in sections for w in s["works"]]
        work2 = next(w for w in all_works if w["raw_cat_no"] == "2")

        _set_override(
            client,
            import_id,
            work2["id"],
            artist_name_override="Override Artist",
            medium_override="Watercolour",
            edition_total_override=50,
        )

        r = _do_reimport(client, import_id)
        assert r.json()["overrides_preserved"] == 1

        sections = _get_sections(client, import_id)
        all_works = [w for s in sections for w in s["works"]]
        work2_new = next(w for w in all_works if w["raw_cat_no"] == "2")
        ovr = work2_new["override"]
        assert ovr["artist_name_override"] == "Override Artist"
        assert ovr["medium_override"] == "Watercolour"
        assert ovr["edition_total_override"] == 50

    def test_include_in_export_preserved(self, client, db_session):
        import_id = _do_import(client)
        sections = _get_sections(client, import_id)
        all_works = [w for s in sections for w in s["works"]]
        work1 = next(w for w in all_works if w["raw_cat_no"] == "1")

        # Exclude cat_no 1 via direct DB update
        uid = _uuid.UUID(work1["id"])
        w = db_session.query(Work).filter(Work.id == uid).one()
        w.include_in_export = False
        db_session.commit()

        # Verify excluded
        sections = _get_sections(client, import_id)
        work1_check = next(
            w for s in sections for w in s["works"] if w["raw_cat_no"] == "1"
        )
        assert work1_check["include_in_export"] is False

        # Reimport
        _do_reimport(client, import_id)

        # Exclusion should be preserved
        sections = _get_sections(client, import_id)
        work1_after = next(
            w for s in sections for w in s["works"] if w["raw_cat_no"] == "1"
        )
        assert work1_after["include_in_export"] is False

    def test_override_lost_for_removed_work(self, client):
        import_id = _do_import(client)
        sections = _get_sections(client, import_id)
        all_works = [w for s in sections for w in s["works"]]
        work3 = next(w for w in all_works if w["raw_cat_no"] == "3")

        # Set override on cat_no 3, which will be removed in reimport
        _set_override(client, import_id, work3["id"], title_override="Will Be Lost")

        r = _do_reimport(client, import_id)
        data = r.json()
        # cat_no 3 is not in the new spreadsheet, so override is not preserved
        assert data["removed"] == 1
        assert data["overrides_preserved"] == 0

    def test_no_overrides_all_new(self, client):
        import_id = _do_import(client)

        # Reimport with completely new cat_nos
        rows = [
            [10, "Gallery X", "Brand New", "New Artist", "100", None, None, None],
        ]
        r = _do_reimport(client, import_id, rows=rows)
        data = r.json()
        assert data["matched"] == 0
        assert data["added"] == 1
        assert data["removed"] == 3  # all 3 originals removed
        assert data["overrides_preserved"] == 0


class TestReimportEdgeCases:
    """Edge cases and error handling."""

    def test_reimport_nonexistent_import(self, client):
        fake_id = str(_uuid.uuid4())
        buf = _make_xlsx(ALL_HEADERS, [[1, "G", "T", "A", "100", None, None, None]])
        r = client.put(
            f"/imports/{fake_id}/reimport",
            files={
                "file": (
                    "test.xlsx",
                    buf,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        assert r.status_code == 404

    def test_reimport_invalid_file(self, client):
        import_id = _do_import(client)
        buf = io.BytesIO(b"not an excel file")
        r = client.put(
            f"/imports/{import_id}/reimport",
            files={
                "file": (
                    "bad.xlsx",
                    buf,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        assert r.status_code == 400

    def test_reimport_missing_required_columns(self, client):
        import_id = _do_import(client)
        buf = _make_xlsx(["Foo", "Bar"], [["a", "b"]])
        r = client.put(
            f"/imports/{import_id}/reimport",
            files={
                "file": (
                    "missing.xlsx",
                    buf,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        assert r.status_code == 400

    def test_reimport_preserves_data_on_invalid_file(self, client):
        """Original data should survive if the new file is invalid."""
        import_id = _do_import(client)
        sections_before = _get_sections(client, import_id)
        total_before = sum(len(s["works"]) for s in sections_before)

        buf = io.BytesIO(b"corrupt")
        client.put(
            f"/imports/{import_id}/reimport",
            files={
                "file": (
                    "bad.xlsx",
                    buf,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )

        # Data should be unchanged
        sections_after = _get_sections(client, import_id)
        total_after = sum(len(s["works"]) for s in sections_after)
        assert total_after == total_before

    def test_reimport_works_without_cat_no(self, client):
        """Works without a cat_no should be treated as new (not matched)."""
        # Import with a work that has no cat_no
        rows = [
            [None, "Gallery A", "No Number", "Artist", "100", None, None, None],
        ]
        import_id = _do_import(client, rows=rows)

        # Reimport — also has a work without cat_no
        new_rows = [
            [None, "Gallery A", "Also No Number", "Artist B", "200", None, None, None],
        ]
        r = _do_reimport(client, import_id, rows=new_rows)
        data = r.json()
        # Cat no is None so nothing matches — original is "removed" (stats-wise
        # it doesn't count because we can't track None keys) and new is "added"
        assert data["added"] == 1
        assert data["matched"] == 0

    def test_reimport_duplicate_cat_no_in_new_spreadsheet(self, client):
        """If the new spreadsheet has duplicate cat_nos, only the first gets the override."""
        import_id = _do_import(client)
        sections = _get_sections(client, import_id)
        all_works = [w for s in sections for w in s["works"]]
        work1 = next(w for w in all_works if w["raw_cat_no"] == "1")
        _set_override(client, import_id, work1["id"], title_override="Keep This")

        # Reimport with two rows having cat_no 1
        rows = [
            [1, "Gallery A", "First", "Artist A", "100", None, None, None],
            [1, "Gallery A", "Second (duplicate)", "Artist B", "200", None, None, None],
        ]
        r = _do_reimport(client, import_id, rows=rows)
        data = r.json()
        assert data["overrides_preserved"] == 1

        # Only the first row with cat_no 1 should have the override
        sections = _get_sections(client, import_id)
        all_works = [w for s in sections for w in s["works"]]
        works_with_cat1 = [w for w in all_works if w["raw_cat_no"] == "1"]
        assert len(works_with_cat1) == 2
        overridden = [w for w in works_with_cat1 if w["override"] is not None]
        assert len(overridden) == 1
        assert overridden[0]["override"]["title_override"] == "Keep This"


class TestReimportAuditAndWarnings:
    """Audit log and warning regeneration."""

    def test_reimport_creates_audit_log(self, client, db_session):
        import_id = _do_import(client)
        _do_reimport(client, import_id)

        uid = _uuid.UUID(import_id)
        logs = (
            db_session.query(AuditLog)
            .filter(AuditLog.import_id == uid, AuditLog.action == "reimport")
            .all()
        )
        assert len(logs) == 1
        assert "matched=" in logs[0].new_value

    def test_reimport_regenerates_warnings(self, client, db_session):
        import_id = _do_import(client)

        # Check initial warnings
        r1 = client.get(f"/imports/{import_id}/warnings")
        warnings_before = r1.json()

        # Reimport with a work that triggers a warning (NFS price)
        rows = [
            [1, "Gallery A", "Title", "Artist", "NFS", None, None, None],
        ]
        _do_reimport(client, import_id, rows=rows)

        r2 = client.get(f"/imports/{import_id}/warnings")
        warnings_after = r2.json()
        # Old warnings should be gone, new ones generated
        old_ids = {w["id"] for w in warnings_before}
        new_ids = {w["id"] for w in warnings_after}
        assert old_ids.isdisjoint(new_ids), "Old warnings should have been replaced"

    def test_reimport_twice(self, client):
        """Re-importing multiple times should work correctly each time."""
        import_id = _do_import(client)

        # First reimport
        r1 = _do_reimport(client, import_id)
        assert r1.status_code == 200

        # Set override on new data
        sections = _get_sections(client, import_id)
        all_works = [w for s in sections for w in s["works"]]
        work1 = next(w for w in all_works if w["raw_cat_no"] == "1")
        _set_override(
            client, import_id, work1["id"], title_override="After First Reimport"
        )

        # Second reimport — override should still be preserved
        r2 = _do_reimport(client, import_id)
        assert r2.status_code == 200
        data = r2.json()
        assert data["overrides_preserved"] == 1

        sections = _get_sections(client, import_id)
        all_works = [w for s in sections for w in s["works"]]
        work1_final = next(w for w in all_works if w["raw_cat_no"] == "1")
        assert work1_final["override"]["title_override"] == "After First Reimport"
