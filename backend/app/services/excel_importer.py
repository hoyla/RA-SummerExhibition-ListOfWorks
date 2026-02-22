from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from sqlalchemy.orm import Session
from difflib import get_close_matches

from backend.app.models.import_model import Import
from backend.app.models.section_model import Section
from backend.app.models.work_model import Work
from backend.app.models.validation_warning_model import ValidationWarning
from typing import List, Optional

from backend.app.services.normalisation_service import (
    normalise_work,
    collect_work_warnings,
)


# ---------------------------------------------------------------------------
# Expected column headers
# ---------------------------------------------------------------------------

REQUIRED_COLUMNS = {"Cat No", "Title", "Artist"}
KNOWN_COLUMNS = {
    "Cat No",
    "Gallery",
    "Title",
    "Artist",
    "Price",
    "Edition",
    "Artwork",
    "Medium",
}


class ImportError(Exception):
    """Raised when the uploaded file cannot be imported."""

    pass


# ---------------------------------------------------------------------------
# Header validation
# ---------------------------------------------------------------------------


def _validate_headers(headers: list[str]) -> list[str]:
    """Validate spreadsheet headers. Returns a list of warning strings for
    missing optional columns.  Raises ImportError for fatal problems."""

    # Strip empties
    found = {h for h in headers if h}

    if not found:
        raise ImportError(
            "The spreadsheet has no column headers in row 1. "
            "Expected columns: " + ", ".join(sorted(KNOWN_COLUMNS))
        )

    # Check for required columns
    missing_required = REQUIRED_COLUMNS - found
    if missing_required:
        # Try to suggest close matches from what was found
        suggestions = []
        for col in sorted(missing_required):
            matches = get_close_matches(col, list(found), n=1, cutoff=0.6)
            if matches:
                suggestions.append(
                    f'  - "{col}" not found (did you mean "{matches[0]}"?)'
                )
            else:
                suggestions.append(f'  - "{col}" not found')

        raise ImportError(
            "Spreadsheet is missing required column(s):\n"
            + "\n".join(suggestions)
            + f"\n\nFound columns: {', '.join(sorted(found))}"
            + f"\nExpected: {', '.join(sorted(KNOWN_COLUMNS))}"
        )

    # Warnings for missing optional columns
    warnings = []
    missing_optional = (KNOWN_COLUMNS - REQUIRED_COLUMNS) - found
    for col in sorted(missing_optional):
        matches = get_close_matches(col, list(found), n=1, cutoff=0.6)
        hint = f' (did you mean "{matches[0]}"?)' if matches else ""
        warnings.append(f'Optional column "{col}" not found{hint}')

    return warnings


def import_excel(
    file_path: str,
    db: Session,
    honorific_tokens: Optional[List[str]] = None,
    display_name: Optional[str] = None,
) -> Import:
    # --- Open workbook (catch corrupt / non-Excel files) ---
    try:
        workbook = load_workbook(filename=file_path, data_only=True)
    except InvalidFileException:
        raise ImportError("The uploaded file is not a valid Excel (.xlsx) file.")
    except Exception as exc:
        raise ImportError(f"Could not read the uploaded file: {exc}")

    sheet = workbook.active
    if sheet is None or sheet.max_row is None or sheet.max_row < 1:
        raise ImportError("The spreadsheet is empty (no rows found).")

    # --- Read & validate headers ---
    headers = [str(cell.value).strip() if cell.value else "" for cell in sheet[1]]
    header_warnings = _validate_headers(headers)

    # Use the user-facing display name for the record, falling back to file_path
    record_name = display_name or file_path

    # Duplicate filename detection
    duplicate_detected = (
        db.query(Import).filter(Import.filename == record_name).first() is not None
    )

    import_record = Import(filename=record_name)
    db.add(import_record)
    db.flush()

    # Import-level warning for duplicate filename
    if duplicate_detected:
        db.add(
            ValidationWarning(
                import_id=import_record.id,
                work_id=None,
                warning_type="duplicate_filename",
                message=f"A previous import with filename {file_path!r} already exists",
            )
        )

    # Import-level warnings for missing optional columns
    for msg in header_warnings:
        db.add(
            ValidationWarning(
                import_id=import_record.id,
                work_id=None,
                warning_type="missing_column",
                message=msg,
            )
        )

    sections_map = {}
    section_positions = {}

    def _cell_value(cell):
        """Return the cell's value, restoring a leading apostrophe that Excel
        silently strips when quotePrefix is set on the cell style."""
        v = cell.value
        if cell.quotePrefix and isinstance(v, str):
            v = "'" + v
        return v

    for row in sheet.iter_rows(min_row=2):
        row_dict = {h: _cell_value(c) for h, c in zip(headers, row)}

        raw_cat_no = row_dict.get("Cat No")
        raw_gallery = row_dict.get("Gallery")
        raw_title = row_dict.get("Title")
        raw_artist = row_dict.get("Artist")
        raw_price = row_dict.get("Price")
        raw_edition = row_dict.get("Edition")
        raw_artwork = row_dict.get("Artwork")
        raw_medium = row_dict.get("Medium")

        gallery_name = raw_gallery or "Uncategorised"

        if gallery_name not in sections_map:
            section = Section(
                import_id=import_record.id,
                name=gallery_name,
                position=len(sections_map) + 1,
            )
            db.add(section)
            db.flush()
            sections_map[gallery_name] = section
            section_positions[gallery_name] = 0

        section = sections_map[gallery_name]
        section_positions[gallery_name] += 1

        work = Work(
            import_id=import_record.id,
            section_id=section.id,
            position_in_section=section_positions[gallery_name],
            raw_cat_no=raw_cat_no,
            raw_gallery=raw_gallery,
            raw_title=raw_title,
            raw_artist=raw_artist,
            raw_price=raw_price,
            raw_edition=raw_edition,
            raw_artwork=raw_artwork,
            raw_medium=raw_medium,
        )

        db.add(work)
        normalise_work(work, honorific_tokens=honorific_tokens)
        db.flush()  # ensures work.id is assigned before referencing it in warnings

        # Collect and store work-level validation warnings
        for warning_type, message in collect_work_warnings(work):
            db.add(
                ValidationWarning(
                    import_id=import_record.id,
                    work_id=work.id,
                    warning_type=warning_type,
                    message=message,
                )
            )

    # Warn if spreadsheet had headers but no data rows
    if not sections_map:
        db.add(
            ValidationWarning(
                import_id=import_record.id,
                work_id=None,
                warning_type="empty_spreadsheet",
                message="The spreadsheet has column headers but no data rows.",
            )
        )

    db.commit()
    return import_record
