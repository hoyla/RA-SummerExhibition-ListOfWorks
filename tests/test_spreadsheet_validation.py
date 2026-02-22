"""
Tests for spreadsheet validation during import:
  - Missing / renamed required columns
  - Missing optional columns (warnings, not errors)
  - Non-Excel files
  - Completely empty spreadsheets
  - Header-only spreadsheets (no data rows)
  - Valid spreadsheets still work
"""

import io
import uuid
import pytest
from openpyxl import Workbook
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db import Base
from backend.app.api.import_routes import router, get_db
from backend.app.services.excel_importer import (
    _validate_headers,
    ImportError as ExcelImportError,
    REQUIRED_COLUMNS,
    KNOWN_COLUMNS,
)


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


def _make_xlsx(headers: list[str], rows: list[list] | None = None) -> io.BytesIO:
    """Create an in-memory .xlsx with the given headers and optional data rows."""
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows or []:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _upload(client, file_bytes: io.BytesIO, filename: str = "test.xlsx"):
    return client.post(
        "/import",
        files={
            "file": (
                filename,
                file_bytes,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )


# ===================================================================
# Unit tests for _validate_headers
# ===================================================================


class TestValidateHeaders:
    """Direct unit tests for the header validation logic."""

    def test_all_known_columns_present(self):
        """No errors, no warnings when all columns present."""
        headers = list(KNOWN_COLUMNS)
        warnings = _validate_headers(headers)
        assert warnings == []

    def test_required_only(self):
        """Required columns only → warnings for missing optional columns."""
        headers = list(REQUIRED_COLUMNS)
        warnings = _validate_headers(headers)
        # Should have warnings for each missing optional column
        missing_optional = KNOWN_COLUMNS - REQUIRED_COLUMNS
        assert len(warnings) == len(missing_optional)
        for w in warnings:
            assert "not found" in w

    def test_empty_headers_raises(self):
        """Completely empty header row → ImportError."""
        with pytest.raises(ExcelImportError, match="no column headers"):
            _validate_headers(["", "", ""])

    def test_no_headers_raises(self):
        """No headers at all → ImportError."""
        with pytest.raises(ExcelImportError, match="no column headers"):
            _validate_headers([])

    def test_missing_required_column_raises(self):
        """Missing a required column → ImportError listing what's missing."""
        headers = ["Cat No", "Gallery", "Price", "Edition"]
        with pytest.raises(ExcelImportError, match="Title") as exc_info:
            _validate_headers(headers)
        assert "Artist" in str(exc_info.value)

    def test_single_missing_required(self):
        """Missing just Title → clear error."""
        headers = ["Cat No", "Artist", "Gallery"]
        with pytest.raises(ExcelImportError, match='"Title" not found'):
            _validate_headers(headers)

    def test_close_match_suggestion(self):
        """Misspelled column → suggestion in error message."""
        headers = ["Cat No", "Titel", "Artst"]  # close to Title and Artist
        with pytest.raises(ExcelImportError) as exc_info:
            _validate_headers(headers)
        msg = str(exc_info.value)
        # Should suggest "Titel" for "Title" and/or "Artst" for "Artist"
        assert "did you mean" in msg

    def test_completely_wrong_columns_raises(self):
        """Columns from a totally different spreadsheet → ImportError."""
        headers = ["First Name", "Last Name", "Email", "Phone"]
        with pytest.raises(ExcelImportError, match="missing required"):
            _validate_headers(headers)

    def test_optional_missing_with_close_match(self):
        """Missing optional column with a typo → warning includes suggestion."""
        headers = ["Cat No", "Title", "Artist", "Prise"]  # close to "Price"
        warnings = _validate_headers(headers)
        price_warnings = [w for w in warnings if "Price" in w]
        assert len(price_warnings) == 1
        assert "did you mean" in price_warnings[0]
        assert "Prise" in price_warnings[0]


# ===================================================================
# Integration tests via the upload endpoint
# ===================================================================


class TestUploadValidation:
    """Test the /import endpoint with various invalid files."""

    def test_valid_spreadsheet_succeeds(self, client):
        """Well-formed spreadsheet imports successfully."""
        buf = _make_xlsx(
            ["Cat No", "Gallery", "Title", "Artist", "Price"],
            [["1", "Gallery A", "Sunset", "John Smith", "500"]],
        )
        resp = _upload(client, buf)
        assert resp.status_code == 200
        assert "import_id" in resp.json()

    def test_non_excel_file_returns_400(self, client):
        """Uploading a plain text file returns a clear 400 error."""
        buf = io.BytesIO(b"this is not an excel file at all")
        resp = _upload(client, buf, filename="fake.xlsx")
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "not a valid Excel" in detail or "Could not read" in detail

    def test_missing_required_column_returns_400(self, client):
        """Spreadsheet missing required columns → 400 with details."""
        buf = _make_xlsx(
            ["Cat No", "Gallery", "Price"],  # missing Title, Artist
            [["1", "Gallery A", "500"]],
        )
        resp = _upload(client, buf)
        assert resp.status_code == 400
        body = resp.json()["detail"]
        assert "Title" in body
        assert "Artist" in body

    def test_completely_wrong_columns_returns_400(self, client):
        """Totally wrong spreadsheet layout → 400."""
        buf = _make_xlsx(
            ["Name", "Email", "Department"],
            [["Jane", "jane@example.com", "Sales"]],
        )
        resp = _upload(client, buf)
        assert resp.status_code == 400
        assert "missing required" in resp.json()["detail"].lower()

    def test_renamed_columns_with_suggestion(self, client):
        """Misspelled required columns → 400 with 'did you mean' hint."""
        buf = _make_xlsx(
            ["Cat No", "Titel", "Artst"],  # close to Title, Artist
            [["1", "Sunset", "John"]],
        )
        resp = _upload(client, buf)
        assert resp.status_code == 400
        body = resp.json()["detail"]
        assert "did you mean" in body.lower()

    def test_empty_file_returns_400(self, client):
        """Completely empty (0 bytes) file → 400."""
        buf = io.BytesIO(b"")
        resp = _upload(client, buf, filename="empty.xlsx")
        assert resp.status_code == 400

    def test_header_only_spreadsheet_succeeds_with_warning(self, client, db_session):
        """Headers but no data rows → imports OK but with a warning."""
        buf = _make_xlsx(
            ["Cat No", "Title", "Artist"],
            [],  # no data rows
        )
        resp = _upload(client, buf)
        assert resp.status_code == 200
        import_id = uuid.UUID(resp.json()["import_id"])

        # Check that an empty_spreadsheet warning was generated
        from backend.app.models.validation_warning_model import ValidationWarning

        warnings = (
            db_session.query(ValidationWarning)
            .filter(
                ValidationWarning.import_id == import_id,
                ValidationWarning.warning_type == "empty_spreadsheet",
            )
            .all()
        )
        assert len(warnings) == 1
        assert "no data rows" in warnings[0].message

    def test_missing_optional_columns_generates_warnings(self, client, db_session):
        """Missing optional columns should import OK but store warnings."""
        buf = _make_xlsx(
            [
                "Cat No",
                "Title",
                "Artist",
            ],  # missing Gallery, Price, Edition, Artwork, Medium
            [["1", "Sunset", "John Smith"]],
        )
        resp = _upload(client, buf)
        assert resp.status_code == 200
        import_id = uuid.UUID(resp.json()["import_id"])

        from backend.app.models.validation_warning_model import ValidationWarning

        warnings = (
            db_session.query(ValidationWarning)
            .filter(
                ValidationWarning.import_id == import_id,
                ValidationWarning.warning_type == "missing_column",
            )
            .all()
        )
        # Should have warnings for: Gallery, Price, Edition, Artwork, Medium
        assert len(warnings) == 5
        warning_msgs = " ".join(w.message for w in warnings)
        for col in ["Gallery", "Price", "Edition", "Artwork", "Medium"]:
            assert col in warning_msgs

    def test_extra_columns_are_ignored(self, client):
        """Extra unknown columns are silently ignored."""
        buf = _make_xlsx(
            ["Cat No", "Title", "Artist", "Foo", "Bar", "Extra"],
            [["1", "Sunset", "John", "x", "y", "z"]],
        )
        resp = _upload(client, buf)
        assert resp.status_code == 200

    def test_case_sensitive_headers(self, client):
        """Column matching is case-sensitive: 'cat no' ≠ 'Cat No'."""
        buf = _make_xlsx(
            ["cat no", "title", "artist"],  # wrong case
            [["1", "Sunset", "John"]],
        )
        resp = _upload(client, buf)
        assert resp.status_code == 400
        # But should suggest close matches
        body = resp.json()["detail"]
        assert "did you mean" in body.lower()
