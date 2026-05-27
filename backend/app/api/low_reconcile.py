"""LOW → LPG reconciliation routes.

Diff a corrected InDesign List of Works export against the current database
(the source of truth) to surface data changes made downstream in InDesign, so
they can be carried into the Large Print Guide.

Detection only: these endpoints parse corrected-LOW Tagged Text and return
classified disparities. They never apply changes. Resolution happens via the
existing channels — a corrected-spreadsheet re-import (structural changes) and
then per-work overrides (text changes). See docs/low-tag-reimport-diff-roadmap.md.

Two endpoint families:
- ``POST /imports/{id}/low-tag-diff`` — transient quick check (no persistence).
- ``…/low-tag-snapshots`` — persist an uploaded file (append-only) so its diff
  can be recomputed against the *current* data on every view. As the editor
  applies overrides / re-imports a corrected spreadsheet (in place, same import),
  re-viewing shows the resolved disparities drop off.
"""

from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.api.auth import require_role
from backend.app.api.low_exports import _ruleset_to_export_config
from backend.app.models.import_model import Import
from backend.app.models.low_tag_snapshot_model import LowTagSnapshot
from backend.app.services.export_renderer import (
    _collect_export_data,
    resolve_export_config,
)
from backend.app.services.low_tag_parser import parse_low_tags
from backend.app.services.low_diff import diff_low

router = APIRouter(tags=["reconcile"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_low_import(import_id: UUID, db: Session) -> Import:
    """Fetch a List of Works import or raise 404/400."""
    rec = db.query(Import).filter(Import.id == import_id).first()
    if not rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Import not found"
        )
    if rec.product_type != "list_of_works":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Import {import_id} is not a list_of_works "
            f"(got {rec.product_type})",
        )
    return rec


def _decode(raw: bytes, encoding: str) -> str:
    try:
        return raw.decode(encoding)
    except (UnicodeDecodeError, LookupError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not decode the uploaded file as {encoding!r}: {exc}",
        )


def _diff_payload(
    import_id: UUID,
    text: str,
    template_id: UUID | None,
    filename: str | None,
    db: Session,
) -> dict:
    """Parse ``text`` and diff it against the import's current resolved data.

    Recomputed live every call, so it always reflects the current DB state.
    """
    config = _ruleset_to_export_config(resolve_export_config(db, template_id))
    parsed = parse_low_tags(text, config)
    collected = _collect_export_data(import_id, db)
    result = diff_low(parsed, collected, config)

    db_entries = sum(len(s["works"]) for s in collected)
    warnings: list[str] = []
    if parsed and db_entries and len(parsed) < db_entries * 0.5:
        warnings.append(
            f"Only {len(parsed)} of {db_entries} entries parsed — the chosen "
            f"template's paragraph/character styles may not match this file."
        )
    if not parsed:
        warnings.append(
            "No entries parsed. Check that the template matches the export "
            "template that produced this file, and that the file is InDesign "
            "Tagged Text (<pstyle:>/<cstyle:> or <ParaStyle:>/<CharStyle:>)."
        )

    return {
        "import_id": str(import_id),
        "template_id": str(template_id) if template_id else None,
        "filename": filename,
        "parsed_entries": len(parsed),
        "db_entries": db_entries,
        "warnings": warnings,
        "section_alignment": result.section_alignment,
        "counts": result.counts,
        "findings": [asdict(f) for f in result.findings],
        "cosmetic": [asdict(f) for f in result.cosmetic],
    }


def _snapshot_meta(snap: LowTagSnapshot) -> dict:
    """Lightweight snapshot metadata (excludes the raw text)."""
    return {
        "id": str(snap.id),
        "import_id": str(snap.import_id),
        "template_id": str(snap.template_id) if snap.template_id else None,
        "filename": snap.filename,
        "encoding": snap.encoding,
        "chars": len(snap.raw_text or ""),
        "uploaded_at": snap.uploaded_at.isoformat() if snap.uploaded_at else None,
    }


# ---------------------------------------------------------------------------
# Transient quick check (no persistence)
# ---------------------------------------------------------------------------


@router.post(
    "/imports/{import_id}/low-tag-diff",
    dependencies=[Depends(require_role("editor"))],
)
def low_tag_diff(
    import_id: UUID,
    file: UploadFile = File(...),
    template_id: UUID | None = Query(
        None, description="The export template that produced the LOW file."
    ),
    encoding: str = Query("mac_roman", description="File encoding."),
    db: Session = Depends(get_db),
):
    """Parse an uploaded corrected LOW file and diff it against the import — a
    one-shot check that persists nothing."""
    _get_low_import(import_id, db)
    text = _decode(file.file.read(), encoding)
    return _diff_payload(import_id, text, template_id, file.filename, db)


# ---------------------------------------------------------------------------
# Persisted snapshots
# ---------------------------------------------------------------------------


@router.post(
    "/imports/{import_id}/low-tag-snapshots",
    dependencies=[Depends(require_role("editor"))],
)
def create_low_tag_snapshot(
    import_id: UUID,
    file: UploadFile = File(...),
    template_id: UUID | None = Query(
        None, description="The export template that produced the LOW file."
    ),
    encoding: str = Query("mac_roman", description="File encoding."),
    db: Session = Depends(get_db),
):
    """Persist an uploaded corrected LOW file (append-only) and return its diff
    against the import's current data."""
    _get_low_import(import_id, db)
    text = _decode(file.file.read(), encoding)

    snap = LowTagSnapshot(
        import_id=import_id,
        template_id=template_id,
        filename=file.filename,
        encoding=encoding,
        raw_text=text,
    )
    db.add(snap)
    db.commit()
    db.refresh(snap)

    return {
        "snapshot": _snapshot_meta(snap),
        "diff": _diff_payload(import_id, text, template_id, file.filename, db),
    }


@router.get("/imports/{import_id}/low-tag-snapshots")
def list_low_tag_snapshots(import_id: UUID, db: Session = Depends(get_db)):
    """List the corrected-LOW snapshots uploaded for an import, newest first."""
    _get_low_import(import_id, db)
    snaps = (
        db.query(LowTagSnapshot)
        .filter(LowTagSnapshot.import_id == import_id)
        .order_by(LowTagSnapshot.uploaded_at.desc())
        .all()
    )
    return [_snapshot_meta(s) for s in snaps]


@router.get("/imports/{import_id}/low-tag-snapshots/{snapshot_id}")
def get_low_tag_snapshot_diff(
    import_id: UUID, snapshot_id: UUID, db: Session = Depends(get_db)
):
    """Recompute a stored snapshot's diff against the import's *current* data."""
    _get_low_import(import_id, db)
    snap = (
        db.query(LowTagSnapshot)
        .filter(
            LowTagSnapshot.id == snapshot_id,
            LowTagSnapshot.import_id == import_id,
        )
        .first()
    )
    if not snap:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not found"
        )
    return {
        "snapshot": _snapshot_meta(snap),
        "diff": _diff_payload(
            import_id, snap.raw_text, snap.template_id, snap.filename, db
        ),
    }


@router.delete(
    "/imports/{import_id}/low-tag-snapshots/{snapshot_id}",
    dependencies=[Depends(require_role("editor"))],
)
def delete_low_tag_snapshot(
    import_id: UUID, snapshot_id: UUID, db: Session = Depends(get_db)
):
    """Delete a stored snapshot."""
    _get_low_import(import_id, db)
    snap = (
        db.query(LowTagSnapshot)
        .filter(
            LowTagSnapshot.id == snapshot_id,
            LowTagSnapshot.import_id == import_id,
        )
        .first()
    )
    if not snap:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not found"
        )
    db.delete(snap)
    db.commit()
    return {"deleted": str(snapshot_id)}
