"""
Import management routes: upload, list, sections, preview, warnings, delete.
"""

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import func
import os
import shutil
from typing import List
from uuid import UUID

from backend.app.api.deps import get_db
from backend.app.api.schemas import (
    ImportOut,
    SectionOut,
    WorkOut,
    WorkOverrideOut,
    PreviewSectionOut,
    PreviewWorkOut,
    ValidationWarningOut,
)
from backend.app.models.import_model import Import
from backend.app.models.section_model import Section
from backend.app.models.work_model import Work
from backend.app.models.override_model import WorkOverride
from backend.app.models.validation_warning_model import ValidationWarning
from backend.app.services.excel_importer import import_excel
from backend.app.services.export_renderer import resolve_export_config

router = APIRouter()


@router.post("/import")
def upload_excel(file: UploadFile = File(...), db: Session = Depends(get_db)):
    os.makedirs("uploads", exist_ok=True)
    file_path = f"uploads/{file.filename}"

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    ruleset = resolve_export_config(db)
    honorific_tokens = None
    if ruleset and isinstance(ruleset.config.get("honorific_tokens"), list):
        honorific_tokens = ruleset.config["honorific_tokens"]
    import_record = import_excel(file_path, db, honorific_tokens=honorific_tokens)

    return {"import_id": str(import_record.id)}


@router.get("/imports", response_model=List[ImportOut])
def list_imports(db: Session = Depends(get_db)):
    imports = db.query(Import).order_by(Import.uploaded_at.desc()).all()

    # Batch-fetch section counts, work counts, and override stats in one query each
    section_counts = {
        str(row.import_id): row.cnt
        for row in db.query(Section.import_id, func.count(Section.id).label("cnt"))
        .group_by(Section.import_id)
        .all()
    }
    work_counts = {
        str(row.import_id): row.cnt
        for row in db.query(Work.import_id, func.count(Work.id).label("cnt"))
        .group_by(Work.import_id)
        .all()
    }
    override_stats = {
        str(row.import_id): row
        for row in db.query(
            Work.import_id,
            func.count(WorkOverride.work_id).label("override_count"),
            func.max(WorkOverride.updated_at).label("last_override_at"),
        )
        .join(WorkOverride, WorkOverride.work_id == Work.id)
        .group_by(Work.import_id)
        .all()
    }

    result = []
    for i in imports:
        iid = str(i.id)
        ovr = override_stats.get(iid)
        result.append(
            {
                "id": iid,
                "filename": i.filename,
                "uploaded_at": i.uploaded_at.isoformat(),
                "notes": i.notes,
                "sections": section_counts.get(iid, 0),
                "works": work_counts.get(iid, 0),
                "override_count": ovr.override_count if ovr else 0,
                "last_override_at": (
                    ovr.last_override_at.isoformat()
                    if ovr and ovr.last_override_at
                    else None
                ),
            }
        )

    return result


@router.get("/imports/{import_id}/sections", response_model=List[SectionOut])
def list_sections(import_id: UUID, db: Session = Depends(get_db)):
    sections = (
        db.query(Section)
        .filter(Section.import_id == import_id)
        .order_by(Section.position.asc())
        .all()
    )

    # Fetch all works for this import in one query
    all_works = (
        db.query(Work)
        .filter(Work.import_id == import_id)
        .order_by(Work.section_id, Work.position_in_section)
        .all()
    )

    # Batch-fetch all overrides in one query and build a lookup map
    work_ids = [w.id for w in all_works]
    overrides_raw = (
        db.query(WorkOverride).filter(WorkOverride.work_id.in_(work_ids)).all()
        if work_ids
        else []
    )
    override_map = {str(o.work_id): o for o in overrides_raw}

    # Group works by section_id
    works_by_section: dict = {}
    for w in all_works:
        key = str(w.section_id)
        works_by_section.setdefault(key, []).append(w)

    result: List[SectionOut] = []

    for section in sections:
        works = works_by_section.get(str(section.id), [])
        ovr = override_map.get

        def _ovr_out(o) -> WorkOverrideOut | None:
            if o is None:
                return None
            return WorkOverrideOut(
                title_override=o.title_override,
                artist_name_override=o.artist_name_override,
                artist_honorifics_override=o.artist_honorifics_override,
                price_numeric_override=(
                    float(o.price_numeric_override)
                    if o.price_numeric_override is not None
                    else None
                ),
                price_text_override=o.price_text_override,
                edition_total_override=o.edition_total_override,
                edition_price_numeric_override=(
                    float(o.edition_price_numeric_override)
                    if o.edition_price_numeric_override is not None
                    else None
                ),
                medium_override=o.medium_override,
            )

        work_items = [
            WorkOut(
                id=str(w.id),
                position_in_section=w.position_in_section,
                raw_cat_no=str(w.raw_cat_no) if w.raw_cat_no is not None else None,
                title=w.title,
                artist_name=w.artist_name,
                artist_honorifics=w.artist_honorifics,
                price_text=w.price_text,
                price_numeric=(
                    float(w.price_numeric) if w.price_numeric is not None else None
                ),
                edition_total=w.edition_total,
                edition_price_numeric=(
                    float(w.edition_price_numeric)
                    if w.edition_price_numeric is not None
                    else None
                ),
                artwork=w.artwork,
                medium=w.medium,
                include_in_export=bool(w.include_in_export),
                override=_ovr_out(ovr(str(w.id))),
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


@router.get("/imports/{import_id}/warnings", response_model=List[ValidationWarningOut])
def list_warnings(import_id: UUID, db: Session = Depends(get_db)):
    from sqlalchemy.orm import outerjoin

    rows = (
        db.query(ValidationWarning, Work)
        .outerjoin(Work, Work.id == ValidationWarning.work_id)
        .filter(ValidationWarning.import_id == import_id)
        .order_by(ValidationWarning.created_at.asc())
        .all()
    )

    return [
        ValidationWarningOut(
            id=str(w.id),
            work_id=str(w.work_id) if w.work_id else None,
            warning_type=w.warning_type,
            message=w.message,
            artist_name=work.artist_name if work else None,
            title=work.title if work else None,
            cat_no=str(work.raw_cat_no) if work and work.raw_cat_no else None,
        )
        for w, work in rows
    ]


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
