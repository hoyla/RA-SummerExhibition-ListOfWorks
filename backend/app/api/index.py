"""
Artists' Index routes: upload, list, artists, export, delete, exclude toggle.
"""

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import func
import os
from pathlib import Path
import shutil
import uuid
from typing import List
from uuid import UUID

from backend.app.api.deps import get_db
from backend.app.config import UPLOAD_DIR
from backend.app.services.export_renderer import escape_for_mac_roman
from backend.app.api.schemas import (
    IndexImportOut,
    IndexArtistOut,
    IndexCatNumberOut,
    IndexArtistOverrideIn,
    IndexArtistOverrideOut,
)
from backend.app.models.import_model import Import
from backend.app.models.index_artist_model import IndexArtist
from backend.app.models.index_cat_number_model import IndexCatNumber
from backend.app.models.index_override_model import IndexArtistOverride
from backend.app.models.audit_log_model import AuditLog
from backend.app.services.index_importer import (
    import_index_excel,
    IndexImportError,
)
from backend.app.services.index_override_service import (
    resolve_index_artist,
    build_known_artist_cache,
    lookup_known_artist,
)
from backend.app.services.index_renderer import (
    collect_index_entries,
    render_index_tagged_text,
    IndexExportConfig,
    DEFAULT_INDEX_CONFIG,
    _letter_key,
)

router = APIRouter(prefix="/index", tags=["index"])


def _merged_from_rows(cat_numbers: list) -> list[int] | None:
    """Return sorted unique source_rows if the artist was merged from
    multiple spreadsheet rows, otherwise None."""
    rows = sorted({cn.source_row for cn in cat_numbers if cn.source_row is not None})
    return rows if len(rows) > 1 else None


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


@router.post("/import")
def upload_index_excel(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload an Artists' Index spreadsheet."""
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    original_name = file.filename or "upload.xlsx"
    safe_name = Path(original_name).name
    disk_name = f"{uuid.uuid4().hex}_{safe_name}"
    file_path = os.path.join(UPLOAD_DIR, disk_name)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        import_record = import_index_excel(
            file_path,
            db,
            display_name=original_name,
        )
    except IndexImportError as exc:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    import_record.disk_filename = disk_name
    db.commit()

    return {"import_id": str(import_record.id)}


# ---------------------------------------------------------------------------
# List imports
# ---------------------------------------------------------------------------


@router.get("/imports", response_model=List[IndexImportOut])
def list_index_imports(db: Session = Depends(get_db)):
    """List all Artists' Index imports."""
    imports = (
        db.query(Import)
        .filter(Import.product_type == "artists_index")
        .order_by(Import.uploaded_at.desc())
        .all()
    )

    # Batch-fetch artist counts
    artist_counts = {
        str(row.import_id): row.cnt
        for row in db.query(
            IndexArtist.import_id,
            func.count(IndexArtist.id).label("cnt"),
        )
        .group_by(IndexArtist.import_id)
        .all()
    }

    return [
        IndexImportOut(
            id=str(i.id),
            filename=i.filename,
            uploaded_at=i.uploaded_at.isoformat(),
            notes=i.notes,
            product_type=i.product_type,
            artist_count=artist_counts.get(str(i.id), 0),
        )
        for i in imports
    ]


# ---------------------------------------------------------------------------
# Artists listing
# ---------------------------------------------------------------------------


@router.get(
    "/imports/{import_id}/artists",
    response_model=List[IndexArtistOut],
)
def list_index_artists(import_id: UUID, db: Session = Depends(get_db)):
    """List all artists for an index import, ordered by resolved sort key."""
    _get_index_import_or_404(import_id, db)

    artists = (
        db.query(IndexArtist)
        .filter(IndexArtist.import_id == import_id)
        .order_by(IndexArtist.sort_key, IndexArtist.row_number)
        .all()
    )

    # Batch-fetch all cat numbers for this import
    artist_ids = [a.id for a in artists]
    cat_numbers = (
        db.query(IndexCatNumber)
        .filter(IndexCatNumber.artist_id.in_(artist_ids))
        .order_by(IndexCatNumber.cat_no)
        .all()
        if artist_ids
        else []
    )
    cat_map: dict[str, list] = {}
    for cn in cat_numbers:
        cat_map.setdefault(str(cn.artist_id), []).append(cn)

    # Batch-fetch overrides
    overrides = (
        db.query(IndexArtistOverride)
        .filter(IndexArtistOverride.artist_id.in_(artist_ids))
        .all()
        if artist_ids
        else []
    )
    override_map: dict[str, IndexArtistOverride] = {
        str(o.artist_id): o for o in overrides
    }

    # Build known artist cache
    known_cache = build_known_artist_cache(db)

    result = []
    for a in artists:
        known = lookup_known_artist(known_cache, a.raw_first_name, a.raw_last_name)
        eff = resolve_index_artist(a, override_map.get(str(a.id)), known)
        result.append(
            IndexArtistOut(
                id=str(a.id),
                row_number=a.row_number,
                raw_title=a.raw_title,
                raw_first_name=a.raw_first_name,
                raw_last_name=a.raw_last_name,
                raw_quals=a.raw_quals,
                raw_company=a.raw_company,
                raw_address=a.raw_address,
                index_name=eff.index_name,
                title=eff.title,
                first_name=eff.first_name,
                last_name=eff.last_name,
                quals=eff.quals,
                company=eff.company,
                second_artist=eff.second_artist,
                is_ra_member=eff.is_ra_member,
                is_company=eff.is_company,
                is_company_auto=eff.is_company_auto,
                has_known_artist=known is not None,
                has_override=str(a.id) in override_map,
                sort_key=eff.sort_key,
                include_in_export=eff.include_in_export,
                cat_numbers=[
                    IndexCatNumberOut(
                        id=str(cn.id),
                        cat_no=cn.cat_no,
                        courtesy=cn.courtesy,
                        source_row=cn.source_row,
                    )
                    for cn in cat_map.get(str(a.id), [])
                ],
                merged_from_rows=_merged_from_rows(cat_map.get(str(a.id), [])),
            )
        )

    # Re-sort by resolved sort key (known artists may change ordering)
    result.sort(key=lambda r: (r.sort_key, r.row_number or 0))
    return result


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def _resolve_index_template(
    db: Session, template_id: UUID | None
) -> "IndexExportConfig":
    """Load an index template by ID and convert to IndexExportConfig."""
    if not template_id:
        return DEFAULT_INDEX_CONFIG

    from backend.app.models.ruleset_model import Ruleset

    r = (
        db.query(Ruleset)
        .filter(
            Ruleset.id == template_id,
            Ruleset.archived == False,
            Ruleset.config_type == "index_template",
        )
        .first()
    )
    if not r:
        return DEFAULT_INDEX_CONFIG

    cfg = r.config
    return IndexExportConfig(
        entry_style=cfg.get("entry_style", DEFAULT_INDEX_CONFIG.entry_style),
        ra_surname_style=cfg.get(
            "ra_surname_style", DEFAULT_INDEX_CONFIG.ra_surname_style
        ),
        ra_caps_style=cfg.get("ra_caps_style", DEFAULT_INDEX_CONFIG.ra_caps_style),
        cat_no_style=cfg.get("cat_no_style", DEFAULT_INDEX_CONFIG.cat_no_style),
        honorifics_style=cfg.get(
            "honorifics_style", DEFAULT_INDEX_CONFIG.honorifics_style
        ),
        expert_numbers_style=cfg.get(
            "expert_numbers_style", DEFAULT_INDEX_CONFIG.expert_numbers_style
        ),
        quals_lowercase=cfg.get(
            "quals_lowercase", DEFAULT_INDEX_CONFIG.quals_lowercase
        ),
        expert_numbers_enabled=cfg.get(
            "expert_numbers_enabled", DEFAULT_INDEX_CONFIG.expert_numbers_enabled
        ),
        cat_no_separator=cfg.get(
            "cat_no_separator", DEFAULT_INDEX_CONFIG.cat_no_separator
        ),
        cat_no_separator_style=cfg.get(
            "cat_no_separator_style", DEFAULT_INDEX_CONFIG.cat_no_separator_style
        ),
        section_separator=cfg.get(
            "section_separator", DEFAULT_INDEX_CONFIG.section_separator
        ),
        section_separator_style=cfg.get(
            "section_separator_style", DEFAULT_INDEX_CONFIG.section_separator_style
        ),
        letter_heading_enabled=cfg.get(
            "letter_heading_enabled", DEFAULT_INDEX_CONFIG.letter_heading_enabled
        ),
        letter_heading_style=cfg.get(
            "letter_heading_style", DEFAULT_INDEX_CONFIG.letter_heading_style
        ),
    )


@router.get("/imports/{import_id}/export-tags")
def export_index_tags(
    import_id: UUID,
    template_id: UUID | None = Query(None),
    letter: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """Export Artists' Index as InDesign Tagged Text.

    Pass ?letter=A to export only the entries for that letter group.
    """
    _get_index_import_or_404(import_id, db)

    entries = collect_index_entries(db, import_id)
    if letter:
        entries = [e for e in entries if _letter_key(e) == letter.upper()]
    cfg = _resolve_index_template(db, template_id)
    output = render_index_tagged_text(entries, cfg)

    return Response(
        content=escape_for_mac_roman(output).encode("mac_roman"),
        media_type="text/plain",
    )


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


@router.delete("/imports/{import_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_index_import(import_id: UUID, db: Session = Depends(get_db)):
    """Delete an Artists' Index import and all associated data."""
    import_record = _get_index_import_or_404(import_id, db)

    # Remove uploaded file from disk
    _remove_disk_file(import_record.disk_filename)

    db.delete(import_record)
    db.commit()
    return None


# ---------------------------------------------------------------------------
# Index artist overrides (GET / PUT / DELETE)
# ---------------------------------------------------------------------------


_OVERRIDE_TEXT_FIELDS = [
    "first_name_override",
    "last_name_override",
    "title_override",
    "quals_override",
    "second_artist_override",
]


def _override_to_out(override: IndexArtistOverride) -> IndexArtistOverrideOut:
    return IndexArtistOverrideOut(
        artist_id=str(override.artist_id),
        first_name_override=override.first_name_override,
        last_name_override=override.last_name_override,
        title_override=override.title_override,
        quals_override=override.quals_override,
        second_artist_override=override.second_artist_override,
        is_company_override=override.is_company_override,
    )


@router.get(
    "/imports/{import_id}/artists/{artist_id}/override",
    response_model=IndexArtistOverrideOut,
)
def get_index_override(import_id: UUID, artist_id: UUID, db: Session = Depends(get_db)):
    _get_artist_or_404(import_id, artist_id, db)
    override = (
        db.query(IndexArtistOverride)
        .filter(IndexArtistOverride.artist_id == artist_id)
        .first()
    )
    if not override:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No override exists for this artist",
        )
    return _override_to_out(override)


@router.put(
    "/imports/{import_id}/artists/{artist_id}/override",
    response_model=IndexArtistOverrideOut,
)
def set_index_override(
    import_id: UUID,
    artist_id: UUID,
    body: IndexArtistOverrideIn,
    db: Session = Depends(get_db),
):
    artist = _get_artist_or_404(import_id, artist_id, db)
    override = (
        db.query(IndexArtistOverride)
        .filter(IndexArtistOverride.artist_id == artist_id)
        .first()
    )

    fields = body.model_dump()
    audit_entries = []

    if override is None:
        override = IndexArtistOverride(artist_id=artist.id, **fields)
        db.add(override)
        for field, new_val in fields.items():
            if new_val is not None:
                audit_entries.append(
                    AuditLog(
                        import_id=import_id,
                        action="override_set",
                        field=field,
                        old_value=None,
                        new_value=str(new_val),
                    )
                )
    else:
        for field, new_val in fields.items():
            old_val = getattr(override, field)
            if new_val != old_val:
                audit_entries.append(
                    AuditLog(
                        import_id=import_id,
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
    return _override_to_out(override)


@router.delete(
    "/imports/{import_id}/artists/{artist_id}/override",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_index_override(
    import_id: UUID, artist_id: UUID, db: Session = Depends(get_db)
):
    _get_artist_or_404(import_id, artist_id, db)
    override = (
        db.query(IndexArtistOverride)
        .filter(IndexArtistOverride.artist_id == artist_id)
        .first()
    )
    if not override:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No override exists for this artist",
        )
    db.delete(override)
    db.add(
        AuditLog(
            import_id=import_id,
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
    "/imports/{import_id}/artists/{artist_id}/exclude",
    status_code=status.HTTP_200_OK,
)
def set_artist_excluded(
    import_id: UUID,
    artist_id: UUID,
    exclude: bool = Query(...),
    db: Session = Depends(get_db),
):
    """Toggle include_in_export for an index artist."""
    artist = _get_artist_or_404(import_id, artist_id, db)

    old_excluded = not bool(artist.include_in_export)
    new_excluded = exclude

    if old_excluded != new_excluded:
        artist.include_in_export = not new_excluded
        db.add(
            AuditLog(
                import_id=import_id,
                action=(
                    "index_artist_excluded" if new_excluded else "index_artist_included"
                ),
                field="include_in_export",
                old_value=str(not old_excluded),
                new_value=str(not new_excluded),
            )
        )
        db.commit()

    return {
        "artist_id": str(artist_id),
        "include_in_export": not new_excluded,
    }


# ---------------------------------------------------------------------------
# Company toggle
# ---------------------------------------------------------------------------


@router.patch(
    "/imports/{import_id}/artists/{artist_id}/company",
    status_code=status.HTTP_200_OK,
)
def set_artist_company(
    import_id: UUID,
    artist_id: UUID,
    is_company: bool = Query(...),
    db: Session = Depends(get_db),
):
    """Toggle is_company override for an index artist."""
    artist = _get_artist_or_404(import_id, artist_id, db)

    override = (
        db.query(IndexArtistOverride)
        .filter(IndexArtistOverride.artist_id == artist_id)
        .first()
    )

    # Determine old effective value
    old_effective = bool(artist.is_company)
    if override and override.is_company_override is not None:
        old_effective = override.is_company_override

    if old_effective != is_company:
        if override is None:
            override = IndexArtistOverride(
                artist_id=artist_id,
                is_company_override=is_company,
            )
            db.add(override)
        else:
            override.is_company_override = is_company

        db.add(
            AuditLog(
                import_id=import_id,
                action=(
                    "index_artist_company_set"
                    if is_company
                    else "index_artist_company_unset"
                ),
                field="is_company_override",
                old_value=str(old_effective),
                new_value=str(is_company),
            )
        )
        db.commit()

    return {
        "artist_id": str(artist_id),
        "is_company": is_company,
        "is_company_auto": bool(artist.is_company),
    }


# ---------------------------------------------------------------------------
# Unmerge
# ---------------------------------------------------------------------------


@router.post(
    "/imports/{import_id}/artists/{artist_id}/unmerge",
    status_code=status.HTTP_200_OK,
)
def unmerge_artist(
    import_id: UUID,
    artist_id: UUID,
    db: Session = Depends(get_db),
):
    """Split a merged artist back into separate entries, one per source row.

    The original artist record keeps the cat numbers from its own row_number.
    New artist records are created for each additional source row.
    """
    from backend.app.services.index_importer import (
        is_ra_member,
        detect_company,
        build_sort_key,
        parse_multi_artist,
    )

    artist = _get_artist_or_404(import_id, artist_id, db)

    # Group cat numbers by source_row
    cat_numbers = (
        db.query(IndexCatNumber)
        .filter(IndexCatNumber.artist_id == artist_id)
        .order_by(IndexCatNumber.cat_no)
        .all()
    )

    groups: dict[int, list] = {}
    for cn in cat_numbers:
        src = cn.source_row if cn.source_row is not None else artist.row_number
        if src is not None:
            groups.setdefault(src, []).append(cn)

    if len(groups) <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Artist was not merged — nothing to unmerge",
        )

    # The original artist keeps cat numbers from its own row_number
    keep_row = artist.row_number
    if keep_row not in groups:
        # Fall back to the lowest row number
        keep_row = min(groups.keys())

    new_artist_ids = []
    for src_row, cns in sorted(groups.items()):
        if src_row == keep_row:
            # These stay with the original artist — no change needed
            continue

        # Create a new artist cloned from the original
        new_artist = IndexArtist(
            import_id=import_id,
            row_number=src_row,
            raw_title=artist.raw_title,
            raw_first_name=artist.raw_first_name,
            raw_last_name=artist.raw_last_name,
            raw_quals=artist.raw_quals,
            raw_company=artist.raw_company,
            raw_address=artist.raw_address,
            title=artist.title,
            first_name=artist.first_name,
            last_name=artist.last_name,
            quals=artist.quals,
            company=artist.company,
            second_artist=artist.second_artist,
            is_ra_member=artist.is_ra_member,
            is_company=artist.is_company,
            sort_key=artist.sort_key,
        )
        db.add(new_artist)
        db.flush()

        # Move cat numbers to the new artist
        for cn in cns:
            cn.artist_id = new_artist.id

        new_artist_ids.append(str(new_artist.id))

    db.add(
        AuditLog(
            import_id=import_id,
            action="index_artist_unmerged",
            field="unmerge",
            old_value=str(artist_id),
            new_value=",".join(new_artist_ids),
        )
    )
    db.commit()

    return {
        "original_artist_id": str(artist_id),
        "new_artist_ids": new_artist_ids,
    }


# ---------------------------------------------------------------------------
# Warnings
# ---------------------------------------------------------------------------


@router.get("/imports/{import_id}/warnings")
def list_index_warnings(import_id: UUID, db: Session = Depends(get_db)):
    """List validation warnings for an index import."""
    import re as _re

    from backend.app.models.validation_warning_model import ValidationWarning

    _get_index_import_or_404(import_id, db)

    warnings = (
        db.query(ValidationWarning)
        .filter(ValidationWarning.import_id == import_id)
        .order_by(ValidationWarning.created_at.asc())
        .all()
    )

    # Build row_number → artist_id lookup so the frontend can link warnings
    # back to the artist row in the table.
    artists = (
        db.query(IndexArtist.row_number, IndexArtist.id)
        .filter(IndexArtist.import_id == import_id)
        .all()
    )
    row_to_artist = {a.row_number: str(a.id) for a in artists}

    _ROW_RE = _re.compile(r"^Rows? (\d+)")

    result = []
    for w in warnings:
        row_number = None
        artist_id = None
        m = _ROW_RE.match(w.message)
        if m:
            row_number = int(m.group(1))
            artist_id = row_to_artist.get(row_number)
        result.append(
            {
                "id": str(w.id),
                "warning_type": w.warning_type,
                "message": w.message,
                "row_number": row_number,
                "artist_id": artist_id,
            }
        )

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_index_import_or_404(import_id: UUID, db: Session) -> Import:
    """Fetch an Import record, ensuring it is an artists_index type."""
    import_record = db.query(Import).filter(Import.id == import_id).first()
    if not import_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Import not found",
        )
    if import_record.product_type != "artists_index":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Import is not an Artists' Index",
        )
    return import_record


def _get_artist_or_404(
    import_id: UUID,
    artist_id: UUID,
    db: Session,
) -> IndexArtist:
    """Fetch an IndexArtist, ensuring it belongs to the given import."""
    artist = (
        db.query(IndexArtist)
        .filter(IndexArtist.id == artist_id, IndexArtist.import_id == import_id)
        .first()
    )
    if not artist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artist not found in this import",
        )
    return artist


def _remove_disk_file(disk_filename: str | None) -> bool:
    """Delete an uploaded file from disk."""
    if not disk_filename:
        return False
    path = os.path.join(UPLOAD_DIR, disk_filename)
    if os.path.isfile(path):
        os.remove(path)
        return True
    return False
