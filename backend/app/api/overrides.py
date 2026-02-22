"""
Override and exclude/include routes for individual works.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from uuid import UUID

from backend.app.api.deps import get_db
from backend.app.api.schemas import OverrideIn, OverrideOut
from backend.app.models.work_model import Work
from backend.app.models.override_model import WorkOverride
from backend.app.models.audit_log_model import AuditLog

router = APIRouter()


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
