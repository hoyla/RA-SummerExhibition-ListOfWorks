from openpyxl import load_workbook
from sqlalchemy.orm import Session

from backend.app.models.import_model import Import
from backend.app.models.section_model import Section
from backend.app.models.work_model import Work
from backend.app.models.validation_warning_model import ValidationWarning
from typing import List, Optional

from backend.app.services.normalisation_service import (
    normalise_work,
    collect_work_warnings,
)


def import_excel(
    file_path: str, db: Session, honorific_tokens: Optional[List[str]] = None
) -> Import:
    workbook = load_workbook(filename=file_path, data_only=True)
    sheet = workbook.active

    # Duplicate filename detection
    duplicate_detected = (
        db.query(Import).filter(Import.filename == file_path).first() is not None
    )

    import_record = Import(filename=file_path)
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

    sections_map = {}
    section_positions = {}

    headers = [str(cell.value).strip() if cell.value else "" for cell in sheet[1]]

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

    db.commit()
    return import_record
