from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse, JSONResponse, Response
from sqlalchemy.orm import Session
import hashlib
import json
import os
import shutil
from pydantic import BaseModel
from typing import List
from uuid import UUID
from datetime import datetime

from sqlalchemy import func

from backend.app.db import SessionLocal
from backend.app.models.import_model import Import
from backend.app.models.section_model import Section
from backend.app.models.work_model import Work
from backend.app.models.override_model import WorkOverride
from backend.app.models.validation_warning_model import ValidationWarning
from backend.app.models.audit_log_model import AuditLog
from backend.app.models.ruleset_model import Ruleset
from backend.app.services.excel_importer import import_excel
from backend.app.services.normalisation_service import DEFAULT_HONORIFIC_TOKENS
from backend.app.services.export_renderer import (
    render_import_as_tagged_text,
    render_import_as_json,
    render_import_as_xml,
    render_import_as_csv,
    ExportConfig,
    DEFAULT_CONFIG,
    DEFAULT_COMPONENTS,
    ComponentConfig,
    resolve_export_config,
    escape_for_mac_roman,
)
from backend.app.api.auth import require_api_key

router = APIRouter(dependencies=[Depends(require_api_key)])


# Pydantic model for import output
class ImportOut(BaseModel):
    id: str
    filename: str
    uploaded_at: str
    notes: str | None
    sections: int
    works: int
    override_count: int
    last_override_at: str | None

    model_config = {"from_attributes": True}


# Embedded override snapshot attached to each WorkOut
class WorkOverrideOut(BaseModel):
    title_override: str | None = None
    artist_name_override: str | None = None
    artist_honorifics_override: str | None = None
    price_numeric_override: float | None = None
    price_text_override: str | None = None
    edition_total_override: int | None = None
    edition_price_numeric_override: float | None = None
    artwork_override: int | None = None
    medium_override: str | None = None

    model_config = {"from_attributes": True}


# New Pydantic model for work output
class WorkOut(BaseModel):
    id: str
    position_in_section: int
    raw_cat_no: str | None
    title: str | None
    artist_name: str | None
    artist_honorifics: str | None
    price_text: str | None
    price_numeric: float | None
    edition_total: int | None
    edition_price_numeric: float | None
    artwork: int | None
    medium: str | None
    include_in_export: bool
    override: WorkOverrideOut | None = None

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


class ValidationWarningOut(BaseModel):
    id: str
    work_id: str | None
    warning_type: str
    message: str
    artist_name: str | None = None
    title: str | None = None
    cat_no: str | None = None

    model_config = {"from_attributes": True}


class OverrideIn(BaseModel):
    """Request body for setting work overrides. All fields are optional."""

    title_override: str | None = None
    artist_name_override: str | None = None
    artist_honorifics_override: str | None = None
    price_numeric_override: float | None = None
    price_text_override: str | None = None
    edition_total_override: int | None = None
    edition_price_numeric_override: float | None = None
    artwork_override: int | None = None
    medium_override: str | None = None


class OverrideOut(BaseModel):
    work_id: str
    title_override: str | None
    artist_name_override: str | None
    artist_honorifics_override: str | None
    price_numeric_override: float | None
    price_text_override: str | None
    edition_total_override: int | None
    edition_price_numeric_override: float | None
    artwork_override: int | None
    medium_override: str | None

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


# Endpoint to list sections and works for an import
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


# ---------------------------------------------------------------------------
# Override endpoints
# ---------------------------------------------------------------------------


def _get_work_or_404(import_id: UUID, work_id: UUID, db: Session):
    work = (
        db.query(Work).filter(Work.id == work_id, Work.import_id == import_id).first()
    )
    if not work:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Work not found in this import",
        )
    return work


@router.get("/imports/{import_id}/works/{work_id}/override", response_model=OverrideOut)
def get_override(import_id: UUID, work_id: UUID, db: Session = Depends(get_db)):
    _get_work_or_404(import_id, work_id, db)
    override = db.query(WorkOverride).filter(WorkOverride.work_id == work_id).first()
    if not override:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No override exists for this work",
        )
    return OverrideOut(
        work_id=str(override.work_id),
        title_override=override.title_override,
        artist_name_override=override.artist_name_override,
        artist_honorifics_override=override.artist_honorifics_override,
        price_numeric_override=(
            float(override.price_numeric_override)
            if override.price_numeric_override is not None
            else None
        ),
        price_text_override=override.price_text_override,
        edition_total_override=override.edition_total_override,
        edition_price_numeric_override=(
            float(override.edition_price_numeric_override)
            if override.edition_price_numeric_override is not None
            else None
        ),
        artwork_override=override.artwork_override,
        medium_override=override.medium_override,
    )


@router.put("/imports/{import_id}/works/{work_id}/override", response_model=OverrideOut)
def set_override(
    import_id: UUID,
    work_id: UUID,
    body: OverrideIn,
    db: Session = Depends(get_db),
):
    work = _get_work_or_404(import_id, work_id, db)
    override = db.query(WorkOverride).filter(WorkOverride.work_id == work_id).first()

    fields = body.model_dump()
    audit_entries = []

    if override is None:
        # Create new override
        override = WorkOverride(work_id=work.id, **fields)
        db.add(override)
        for field, new_val in fields.items():
            if new_val is not None:
                audit_entries.append(
                    AuditLog(
                        import_id=import_id,
                        work_id=work_id,
                        action="override_set",
                        field=field,
                        old_value=None,
                        new_value=str(new_val),
                    )
                )
    else:
        # Update existing override, log changed fields
        for field, new_val in fields.items():
            old_val = getattr(override, field)
            if new_val != old_val:
                audit_entries.append(
                    AuditLog(
                        import_id=import_id,
                        work_id=work_id,
                        action="override_set",
                        field=field,
                        old_value=str(old_val) if old_val is not None else None,
                        new_value=str(new_val) if new_val is not None else None,
                    )
                )
                setattr(override, field, new_val)

    for entry in audit_entries:
        db.add(entry)

    db.commit()
    db.refresh(override)

    return OverrideOut(
        work_id=str(override.work_id),
        title_override=override.title_override,
        artist_name_override=override.artist_name_override,
        artist_honorifics_override=override.artist_honorifics_override,
        price_numeric_override=(
            float(override.price_numeric_override)
            if override.price_numeric_override is not None
            else None
        ),
        price_text_override=override.price_text_override,
        edition_total_override=override.edition_total_override,
        edition_price_numeric_override=(
            float(override.edition_price_numeric_override)
            if override.edition_price_numeric_override is not None
            else None
        ),
        artwork_override=override.artwork_override,
        medium_override=override.medium_override,
    )


@router.delete(
    "/imports/{import_id}/works/{work_id}/override",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_override(import_id: UUID, work_id: UUID, db: Session = Depends(get_db)):
    _get_work_or_404(import_id, work_id, db)
    override = db.query(WorkOverride).filter(WorkOverride.work_id == work_id).first()
    if not override:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No override exists for this work",
        )
    db.delete(override)
    db.add(
        AuditLog(
            import_id=import_id,
            work_id=work_id,
            action="override_deleted",
            field=None,
            old_value=None,
            new_value=None,
        )
    )
    db.commit()
    return None


# ---------------------------------------------------------------------------
# Exclude / include toggle
# ---------------------------------------------------------------------------


@router.patch(
    "/imports/{import_id}/works/{work_id}/exclude",
    status_code=status.HTTP_200_OK,
)
def set_work_excluded(
    import_id: UUID,
    work_id: UUID,
    exclude: bool,
    db: Session = Depends(get_db),
):
    """
    Set include_in_export on a work.
    Pass ?exclude=true to exclude, ?exclude=false to re-include.
    """
    work = _get_work_or_404(import_id, work_id, db)

    old_value = not bool(work.include_in_export)  # old excluded state
    new_excluded = exclude

    if old_value != new_excluded:
        work.include_in_export = not new_excluded
        db.add(
            AuditLog(
                import_id=import_id,
                work_id=work_id,
                action="work_excluded" if new_excluded else "work_included",
                field="include_in_export",
                old_value=str(not old_value),
                new_value=str(not new_excluded),
            )
        )
        db.commit()

    return {"work_id": str(work_id), "include_in_export": not new_excluded}


@router.get("/config")
def get_config(db: Session = Depends(get_db)):
    """Return the active export configuration (or built-in defaults)."""
    ruleset = resolve_export_config(db)
    cfg = ruleset.config if ruleset else {}
    return {
        "currency_symbol": cfg.get("currency_symbol", DEFAULT_CONFIG.currency_symbol),
        "section_style": cfg.get("section_style", DEFAULT_CONFIG.section_style),
        "entry_style": cfg.get("entry_style", DEFAULT_CONFIG.entry_style),
        "edition_prefix": cfg.get("edition_prefix", DEFAULT_CONFIG.edition_prefix),
        "edition_brackets": cfg.get(
            "edition_brackets", DEFAULT_CONFIG.edition_brackets
        ),
        "cat_no_style": cfg.get("cat_no_style", DEFAULT_CONFIG.cat_no_style),
        "artist_style": cfg.get("artist_style", DEFAULT_CONFIG.artist_style),
        "honorifics_style": cfg.get(
            "honorifics_style", DEFAULT_CONFIG.honorifics_style
        ),
        "honorifics_lowercase": cfg.get(
            "honorifics_lowercase", DEFAULT_CONFIG.honorifics_lowercase
        ),
        "title_style": cfg.get("title_style", DEFAULT_CONFIG.title_style),
        "price_style": cfg.get("price_style", DEFAULT_CONFIG.price_style),
        "medium_style": cfg.get("medium_style", DEFAULT_CONFIG.medium_style),
        "artwork_style": cfg.get("artwork_style", DEFAULT_CONFIG.artwork_style),
        "thousands_separator": cfg.get(
            "thousands_separator", DEFAULT_CONFIG.thousands_separator
        ),
        "decimal_places": cfg.get("decimal_places", DEFAULT_CONFIG.decimal_places),
        "honorific_tokens": cfg.get("honorific_tokens", DEFAULT_HONORIFIC_TOKENS),
        "leading_separator": cfg.get(
            "leading_separator", DEFAULT_CONFIG.leading_separator
        ),
        "trailing_separator": cfg.get(
            "trailing_separator", DEFAULT_CONFIG.trailing_separator
        ),
        "final_sep_from_last_component": cfg.get(
            "final_sep_from_last_component",
            DEFAULT_CONFIG.final_sep_from_last_component,
        ),
        "components": [
            (
                {
                    "field": c["field"],
                    "separator_after": c.get("separator_after", "tab"),
                    "omit_sep_when_empty": c.get("omit_sep_when_empty", True),
                    "enabled": c.get("enabled", True),
                    "max_line_chars": c.get("max_line_chars", None),
                    "next_component_position": c.get(
                        "next_component_position", "end_of_text"
                    ),
                    "balance_lines": c.get("balance_lines", False),
                }
                if isinstance(c, dict)
                else {
                    "field": c.field,
                    "separator_after": c.separator_after,
                    "omit_sep_when_empty": c.omit_sep_when_empty,
                    "enabled": c.enabled,
                    "max_line_chars": c.max_line_chars,
                    "next_component_position": c.next_component_position,
                    "balance_lines": c.balance_lines,
                }
            )
            for c in cfg.get(
                "components",
                [
                    {
                        "field": c.field,
                        "separator_after": c.separator_after,
                        "omit_sep_when_empty": c.omit_sep_when_empty,
                        "enabled": c.enabled,
                        "max_line_chars": c.max_line_chars,
                        "next_component_position": c.next_component_position,
                        "balance_lines": c.balance_lines,
                    }
                    for c in DEFAULT_COMPONENTS
                ],
            )
        ],
    }


class ComponentConfigIn(BaseModel):
    field: str
    separator_after: str = "tab"
    omit_sep_when_empty: bool = True
    enabled: bool = True
    max_line_chars: int | None = None
    next_component_position: str = "end_of_text"
    balance_lines: bool = False


class ConfigIn(BaseModel):
    honorific_tokens: list[str] = [
        "RA",
        "PRA",
        "PPRA",
        "HON",
        "HONRA",
        "ELECT",
        "EX",
        "OFFICIO",
    ]
    currency_symbol: str = "£"
    section_style: str = "SectionTitle"
    entry_style: str = "CatalogueEntry"
    edition_prefix: str = "edition of"
    edition_brackets: bool = True
    cat_no_style: str = "CatNo"
    artist_style: str = "ArtistName"
    honorifics_style: str = "Honorifics"
    honorifics_lowercase: bool = False
    title_style: str = "WorkTitle"
    price_style: str = "Price"
    medium_style: str = "Medium"
    artwork_style: str = "Artwork"
    thousands_separator: str = ","
    decimal_places: int = 0
    leading_separator: str = "none"
    trailing_separator: str = "none"
    final_sep_from_last_component: bool = False
    components: list[ComponentConfigIn] = [
        ComponentConfigIn(field="work_number", separator_after="tab"),
        ComponentConfigIn(field="artist", separator_after="tab"),
        ComponentConfigIn(field="title", separator_after="tab"),
        ComponentConfigIn(field="edition", separator_after="tab"),
        ComponentConfigIn(field="artwork", separator_after="tab", enabled=False),
        ComponentConfigIn(field="price", separator_after="none"),
        ComponentConfigIn(field="medium", separator_after="none"),
    ]


@router.put("/config")
def put_config(body: ConfigIn, db: Session = Depends(get_db)):
    """Save (replace) the active export configuration."""
    config_dict = body.model_dump()
    config_hash = hashlib.sha256(
        json.dumps(config_dict, sort_keys=True).encode()
    ).hexdigest()
    # Archive previous active rulesets
    db.query(Ruleset).filter(Ruleset.archived == False).update({"archived": True})
    ruleset = Ruleset(name="active", config=config_dict, config_hash=config_hash)
    db.add(ruleset)
    db.commit()
    return config_dict


@router.get("/imports/{import_id}/export-tags")
def export_indesign_tags(import_id: UUID, db: Session = Depends(get_db)):
    ruleset = resolve_export_config(db)
    config = DEFAULT_CONFIG
    if ruleset:
        cfg = ruleset.config
        raw_components = cfg.get(
            "components",
            [
                {
                    "field": c.field,
                    "separator_after": c.separator_after,
                    "omit_sep_when_empty": c.omit_sep_when_empty,
                    "enabled": c.enabled,
                    "max_line_chars": c.max_line_chars,
                    "next_component_position": c.next_component_position,
                    "balance_lines": c.balance_lines,
                }
                for c in DEFAULT_COMPONENTS
            ],
        )
        components = [
            ComponentConfig(
                field=c["field"] if isinstance(c, dict) else c.field,
                separator_after=(
                    c.get("separator_after", "tab")
                    if isinstance(c, dict)
                    else c.separator_after
                ),
                omit_sep_when_empty=(
                    c.get("omit_sep_when_empty", True)
                    if isinstance(c, dict)
                    else c.omit_sep_when_empty
                ),
                enabled=(c.get("enabled", True) if isinstance(c, dict) else c.enabled),
                max_line_chars=(
                    c.get("max_line_chars", None)
                    if isinstance(c, dict)
                    else c.max_line_chars
                ),
                next_component_position=(
                    c.get("next_component_position", "end_of_text")
                    if isinstance(c, dict)
                    else c.next_component_position
                ),
                balance_lines=(
                    c.get("balance_lines", False)
                    if isinstance(c, dict)
                    else c.balance_lines
                ),
            )
            for c in raw_components
        ]
        config = ExportConfig(
            currency_symbol=cfg.get("currency_symbol", DEFAULT_CONFIG.currency_symbol),
            section_style=cfg.get("section_style", DEFAULT_CONFIG.section_style),
            entry_style=cfg.get("entry_style", DEFAULT_CONFIG.entry_style),
            edition_prefix=cfg.get("edition_prefix", DEFAULT_CONFIG.edition_prefix),
            edition_brackets=cfg.get(
                "edition_brackets", DEFAULT_CONFIG.edition_brackets
            ),
            cat_no_style=cfg.get("cat_no_style", DEFAULT_CONFIG.cat_no_style),
            artist_style=cfg.get("artist_style", DEFAULT_CONFIG.artist_style),
            honorifics_style=cfg.get(
                "honorifics_style", DEFAULT_CONFIG.honorifics_style
            ),
            honorifics_lowercase=cfg.get(
                "honorifics_lowercase", DEFAULT_CONFIG.honorifics_lowercase
            ),
            title_style=cfg.get("title_style", DEFAULT_CONFIG.title_style),
            price_style=cfg.get("price_style", DEFAULT_CONFIG.price_style),
            medium_style=cfg.get("medium_style", DEFAULT_CONFIG.medium_style),
            artwork_style=cfg.get("artwork_style", DEFAULT_CONFIG.artwork_style),
            thousands_separator=cfg.get(
                "thousands_separator", DEFAULT_CONFIG.thousands_separator
            ),
            decimal_places=cfg.get("decimal_places", DEFAULT_CONFIG.decimal_places),
            leading_separator=cfg.get(
                "leading_separator", DEFAULT_CONFIG.leading_separator
            ),
            trailing_separator=cfg.get(
                "trailing_separator", DEFAULT_CONFIG.trailing_separator
            ),
            final_sep_from_last_component=cfg.get(
                "final_sep_from_last_component",
                DEFAULT_CONFIG.final_sep_from_last_component,
            ),
            components=components,
        )
    output = render_import_as_tagged_text(import_id, db, config)
    return Response(
        content=escape_for_mac_roman(output).encode("mac_roman"),
        media_type="text/plain",
    )


@router.get("/imports/{import_id}/sections/{section_id}/export-tags")
def export_section_indesign_tags(
    import_id: UUID, section_id: UUID, db: Session = Depends(get_db)
):
    """Export InDesign Tagged Text for a single section only."""
    ruleset = resolve_export_config(db)
    config = DEFAULT_CONFIG
    if ruleset:
        cfg = ruleset.config
        raw_components = cfg.get(
            "components",
            [
                {
                    "field": c.field,
                    "separator_after": c.separator_after,
                    "omit_sep_when_empty": c.omit_sep_when_empty,
                    "enabled": c.enabled,
                    "max_line_chars": c.max_line_chars,
                    "next_component_position": c.next_component_position,
                    "balance_lines": c.balance_lines,
                }
                for c in DEFAULT_COMPONENTS
            ],
        )
        components = [
            ComponentConfig(
                field=c["field"] if isinstance(c, dict) else c.field,
                separator_after=(
                    c.get("separator_after", "tab")
                    if isinstance(c, dict)
                    else c.separator_after
                ),
                omit_sep_when_empty=(
                    c.get("omit_sep_when_empty", True)
                    if isinstance(c, dict)
                    else c.omit_sep_when_empty
                ),
                enabled=(c.get("enabled", True) if isinstance(c, dict) else c.enabled),
                max_line_chars=(
                    c.get("max_line_chars", None)
                    if isinstance(c, dict)
                    else c.max_line_chars
                ),
                next_component_position=(
                    c.get("next_component_position", "end_of_text")
                    if isinstance(c, dict)
                    else c.next_component_position
                ),
                balance_lines=(
                    c.get("balance_lines", False)
                    if isinstance(c, dict)
                    else c.balance_lines
                ),
            )
            for c in raw_components
        ]
        config = ExportConfig(
            currency_symbol=cfg.get("currency_symbol", DEFAULT_CONFIG.currency_symbol),
            section_style=cfg.get("section_style", DEFAULT_CONFIG.section_style),
            entry_style=cfg.get("entry_style", DEFAULT_CONFIG.entry_style),
            edition_prefix=cfg.get("edition_prefix", DEFAULT_CONFIG.edition_prefix),
            edition_brackets=cfg.get(
                "edition_brackets", DEFAULT_CONFIG.edition_brackets
            ),
            cat_no_style=cfg.get("cat_no_style", DEFAULT_CONFIG.cat_no_style),
            artist_style=cfg.get("artist_style", DEFAULT_CONFIG.artist_style),
            honorifics_style=cfg.get(
                "honorifics_style", DEFAULT_CONFIG.honorifics_style
            ),
            honorifics_lowercase=cfg.get(
                "honorifics_lowercase", DEFAULT_CONFIG.honorifics_lowercase
            ),
            title_style=cfg.get("title_style", DEFAULT_CONFIG.title_style),
            price_style=cfg.get("price_style", DEFAULT_CONFIG.price_style),
            medium_style=cfg.get("medium_style", DEFAULT_CONFIG.medium_style),
            artwork_style=cfg.get("artwork_style", DEFAULT_CONFIG.artwork_style),
            thousands_separator=cfg.get(
                "thousands_separator", DEFAULT_CONFIG.thousands_separator
            ),
            decimal_places=cfg.get("decimal_places", DEFAULT_CONFIG.decimal_places),
            leading_separator=cfg.get(
                "leading_separator", DEFAULT_CONFIG.leading_separator
            ),
            trailing_separator=cfg.get(
                "trailing_separator", DEFAULT_CONFIG.trailing_separator
            ),
            final_sep_from_last_component=cfg.get(
                "final_sep_from_last_component",
                DEFAULT_CONFIG.final_sep_from_last_component,
            ),
            components=components,
        )
    output = render_import_as_tagged_text(import_id, db, config, section_id=section_id)
    return Response(
        content=escape_for_mac_roman(output).encode("mac_roman"),
        media_type="text/plain",
    )


@router.get("/imports/{import_id}/export-json")
def export_json(import_id: UUID, db: Session = Depends(get_db)):
    output = render_import_as_json(import_id, db)
    return Response(content=output, media_type="application/json")


@router.get("/imports/{import_id}/export-xml")
def export_xml(import_id: UUID, db: Session = Depends(get_db)):
    output = render_import_as_xml(import_id, db)
    return Response(content=output, media_type="application/xml")


@router.get("/imports/{import_id}/export-csv")
def export_csv(import_id: UUID, db: Session = Depends(get_db)):
    output = render_import_as_csv(import_id, db)
    return Response(content=output, media_type="text/csv")


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
