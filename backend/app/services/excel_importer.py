from openpyxl import load_workbook
from sqlalchemy.orm import Session

from backend.app.models.import_model import Import
from backend.app.models.section_model import Section
from backend.app.models.work_model import Work
from backend.app.services.normalisation_service import normalise_work


def import_excel(file_path: str, db: Session) -> Import:
    workbook = load_workbook(filename=file_path, data_only=True)
    sheet = workbook.active

    import_record = Import(filename=file_path)
    db.add(import_record)
    db.flush()

    sections_map = {}
    section_positions = {}

    headers = [str(cell.value).strip() if cell.value else "" for cell in sheet[1]]

    for row in sheet.iter_rows(min_row=2, values_only=True):
        row_dict = dict(zip(headers, row))

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
        normalise_work(work)

    db.commit()
    return import_record
