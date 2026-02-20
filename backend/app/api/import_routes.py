from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
import os
import shutil
from pydantic import BaseModel
from typing import List
from uuid import UUID
from datetime import datetime

from backend.app.db import SessionLocal
from backend.app.models.import_model import Import
from backend.app.models.section_model import Section
from backend.app.models.work_model import Work
from backend.app.services.excel_importer import import_excel

router = APIRouter()


# Pydantic model for import output
class ImportOut(BaseModel):
    id: str
    filename: str
    uploaded_at: str
    notes: str | None
    sections: int
    works: int

    model_config = {"from_attributes": True}


# New Pydantic model for work output
class WorkOut(BaseModel):
    id: str
    position_in_section: int
    raw_cat_no: str | None
    title: str | None
    artist_name: str | None
    price_text: str | None
    edition_total: int | None

    model_config = {"from_attributes": True}


# New Pydantic model for section output


class SectionOut(BaseModel):
    id: str
    name: str
    position: int
    works: List[WorkOut]

    model_config = {"from_attributes": True}


# Preview Pydantic models
class PreviewWorkOut(BaseModel):
    number: str | None
    title: str | None
    artist: str | None
    price_display: str | None
    edition_display: str | None

    model_config = {"from_attributes": True}


class PreviewSectionOut(BaseModel):
    name: str
    position: int
    works: List[PreviewWorkOut]

    model_config = {"from_attributes": True}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/import")
def upload_excel(file: UploadFile = File(...), db: Session = Depends(get_db)):
    os.makedirs("uploads", exist_ok=True)
    file_path = f"uploads/{file.filename}"

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    import_record = import_excel(file_path, db)

    return {"import_id": str(import_record.id)}


@router.get("/imports", response_model=List[ImportOut])
def list_imports(db: Session = Depends(get_db)):
    imports = db.query(Import).order_by(Import.uploaded_at.desc()).all()

    result = []

    for i in imports:
        section_count = db.query(Section).filter(Section.import_id == i.id).count()

        work_count = db.query(Work).filter(Work.import_id == i.id).count()

        result.append(
            {
                "id": str(i.id),
                "filename": i.filename,
                "uploaded_at": i.uploaded_at.isoformat(),
                "notes": i.notes,
                "sections": section_count,
                "works": work_count,
            }
        )

    return result


# Endpoint to list sections and works for an import
@router.get("/imports/{import_id}/sections", response_model=List[SectionOut])
def list_sections(import_id: UUID, db: Session = Depends(get_db)):
    sections = (
        db.query(Section)
        .filter(Section.import_id == import_id)
        .order_by(Section.position.asc())
        .all()
    )

    result: List[SectionOut] = []

    for section in sections:
        works = (
            db.query(Work)
            .filter(Work.section_id == section.id)
            .order_by(Work.position_in_section.asc())
            .all()
        )

        work_items = [
            WorkOut(
                id=str(w.id),
                position_in_section=w.position_in_section,
                raw_cat_no=str(w.raw_cat_no) if w.raw_cat_no is not None else None,
                title=w.title,
                artist_name=w.artist_name,
                price_text=w.price_text,
                edition_total=w.edition_total,
            )
            for w in works
        ]

        result.append(
            SectionOut(
                id=str(section.id),
                name=section.name,
                position=section.position,
                works=work_items,
            )
        )

    return result


@router.get("/imports/{import_id}/preview", response_model=List[PreviewSectionOut])
def preview_import(import_id: UUID, db: Session = Depends(get_db)):
    sections = (
        db.query(Section)
        .filter(Section.import_id == import_id)
        .order_by(Section.position.asc())
        .all()
    )

    result: List[PreviewSectionOut] = []

    for section in sections:
        works = (
            db.query(Work)
            .filter(Work.section_id == section.id)
            .order_by(Work.position_in_section.asc())
            .all()
        )

        preview_works = []

        for w in works:
            edition_display = None
            if w.edition_total and w.edition_price_numeric:
                edition_display = (
                    f"(edition of {w.edition_total} at £{w.edition_price_numeric})"
                )
            elif w.edition_total:
                edition_display = f"(edition of {w.edition_total})"

            preview_works.append(
                PreviewWorkOut(
                    number=str(w.raw_cat_no) if w.raw_cat_no else None,
                    title=w.title,
                    artist=w.artist_name,
                    price_display=w.price_text,
                    edition_display=edition_display,
                )
            )

        result.append(
            PreviewSectionOut(
                name=section.name,
                position=section.position,
                works=preview_works,
            )
        )

    return result


@router.get("/imports/{import_id}/export-tags")
def export_indesign_tags(import_id: UUID, db: Session = Depends(get_db)):
    sections = (
        db.query(Section)
        .filter(Section.import_id == import_id)
        .order_by(Section.position.asc())
        .all()
    )

    lines = []

    for section in sections:
        # Section heading
        lines.append(f"<ParaStyle:SectionTitle>{section.name}")
        lines.append("\r")

        works = (
            db.query(Work)
            .filter(Work.section_id == section.id)
            .order_by(Work.position_in_section.asc())
            .all()
        )

        for w in works:
            number = str(w.raw_cat_no) if w.raw_cat_no else ""
            title = w.title or ""
            artist = w.artist_name or ""
            price = w.price_text or ""

            edition_display = ""
            if w.edition_total and w.edition_price_numeric:
                edition_display = (
                    f" (edition of {w.edition_total} at £{w.edition_price_numeric})"
                )
            elif w.edition_total:
                edition_display = f" (edition of {w.edition_total})"

            # Catalogue entry paragraph
            lines.append(
                f"<ParaStyle:CatalogueEntry>{number}\t{artist}\t{title}{edition_display}\t{price}"
            )
            lines.append("\r")

        # Extra break after each section
        lines.append("\r")

    return PlainTextResponse(content="".join(lines), media_type="text/plain")


# Endpoint to delete an import (cascades to sections and works)
@router.delete("/imports/{import_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_import(import_id: UUID, db: Session = Depends(get_db)):
    import_record = db.query(Import).filter(Import.id == import_id).first()

    if not import_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Import not found",
        )

    db.delete(import_record)
    db.commit()

    return None
