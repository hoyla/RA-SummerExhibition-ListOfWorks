"""
Audit log routes: per-import and global audit trail.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List
from uuid import UUID

from backend.app.api.deps import get_db
from backend.app.api.schemas import AuditLogOut
from backend.app.models.audit_log_model import AuditLog
from backend.app.models.import_model import Import
from backend.app.models.work_model import Work
from backend.app.models.ruleset_model import Ruleset

router = APIRouter(tags=["audit"])


def _build_audit_response(logs: list[AuditLog], db: Session) -> List[AuditLogOut]:
    """Enrich audit log rows with denormalised work and template context."""
    work_ids = list({log.work_id for log in logs if log.work_id})
    work_map: dict = {}
    if work_ids:
        works = db.query(Work).filter(Work.id.in_(work_ids)).all()
        work_map = {str(w.id): w for w in works}

    template_ids = list({log.template_id for log in logs if log.template_id})
    template_map: dict = {}
    if template_ids:
        templates = db.query(Ruleset).filter(Ruleset.id.in_(template_ids)).all()
        template_map = {str(t.id): t for t in templates}

    result = []
    for log in logs:
        w = work_map.get(str(log.work_id)) if log.work_id else None
        t = template_map.get(str(log.template_id)) if log.template_id else None
        result.append(
            AuditLogOut(
                id=str(log.id),
                import_id=str(log.import_id) if log.import_id else None,
                work_id=str(log.work_id) if log.work_id else None,
                template_id=str(log.template_id) if log.template_id else None,
                action=log.action,
                field=log.field,
                old_value=log.old_value,
                new_value=log.new_value,
                created_at=log.created_at.isoformat(),
                cat_no=str(w.raw_cat_no) if w and w.raw_cat_no is not None else None,
                artist_name=w.artist_name if w else None,
                title=w.title if w else None,
                template_name=t.name if t else None,
            )
        )
    return result


@router.get(
    "/imports/{import_id}/audit-log",
    response_model=List[AuditLogOut],
)
def get_import_audit_log(
    import_id: UUID,
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """Return audit log entries for a single import, newest first."""
    imp = db.query(Import).filter(Import.id == import_id).first()
    if not imp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Import not found"
        )

    logs = (
        db.query(AuditLog)
        .filter(AuditLog.import_id == import_id)
        .order_by(desc(AuditLog.created_at))
        .limit(limit)
        .all()
    )
    return _build_audit_response(logs, db)


@router.get(
    "/audit-log",
    response_model=List[AuditLogOut],
)
def get_global_audit_log(
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """Return the most recent audit log entries across all imports."""
    logs = db.query(AuditLog).order_by(desc(AuditLog.created_at)).limit(limit).all()
    return _build_audit_response(logs, db)
