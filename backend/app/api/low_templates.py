"""
Export template CRUD routes.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session
import hashlib
import json
import re
from typing import List
from uuid import UUID

from backend.app.api.auth import require_role
from backend.app.api.deps import get_db
from backend.app.api.schemas import TemplateBodyIn, TemplateOut
from backend.app.models.ruleset_model import Ruleset
from backend.app.models.audit_log_model import AuditLog

router = APIRouter(tags=["templates"])


@router.get("/templates", response_model=List[TemplateOut])
def list_templates(db: Session = Depends(get_db)):
    """List all non-archived export templates."""
    rows = (
        db.query(Ruleset)
        .filter(Ruleset.archived == False, Ruleset.config_type == "template")
        .order_by(Ruleset.is_builtin.desc(), Ruleset.name.asc())
        .all()
    )
    return [
        TemplateOut(
            id=str(r.id),
            name=r.name,
            created_at=r.created_at.isoformat(),
            is_builtin=r.is_builtin,
        )
        for r in rows
    ]


@router.get(
    "/templates/{template_id}/export",
    dependencies=[Depends(require_role("admin"))],
)
def export_template(template_id: UUID, db: Session = Depends(get_db)):
    """Download a single LoW template as seed-format JSON.

    Reconstructs the ``_name`` metadata field so the file can be
    dropped straight into ``seed_templates/``.
    """
    r = (
        db.query(Ruleset)
        .filter(
            Ruleset.id == template_id,
            Ruleset.archived == False,
            Ruleset.config_type == "template",
        )
        .first()
    )
    if not r:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Template not found"
        )
    seed = {"_name": r.name, **r.config}
    body = json.dumps(seed, indent=2, ensure_ascii=False) + "\n"
    slug = r.slug or re.sub(r"[^a-z0-9]+", "-", r.name.lower()).strip("-")
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{slug}.json"',
        },
    )


@router.get("/templates/{template_id}")
def get_template(template_id: UUID, db: Session = Depends(get_db)):
    """Return full config for one template."""
    r = (
        db.query(Ruleset)
        .filter(Ruleset.id == template_id, Ruleset.archived == False)
        .first()
    )
    if not r:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Template not found"
        )
    return {
        "id": str(r.id),
        "name": r.name,
        "created_at": r.created_at.isoformat(),
        "is_builtin": r.is_builtin,
        **r.config,
    }


@router.post(
    "/templates",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role("editor"))],
)
def create_template(body: TemplateBodyIn, db: Session = Depends(get_db)):
    """Create a new export template."""
    config_dict = body.model_dump(exclude={"name"})
    config_hash = hashlib.sha256(
        json.dumps(config_dict, sort_keys=True).encode()
    ).hexdigest()
    r = Ruleset(
        name=body.name,
        config=config_dict,
        config_hash=config_hash,
        config_type="template",
        is_builtin=False,
    )
    db.add(r)
    db.flush()
    db.add(
        AuditLog(
            template_id=r.id,
            action="template_created",
            new_value=r.name,
        )
    )
    db.commit()
    db.refresh(r)
    return TemplateOut(
        id=str(r.id), name=r.name, created_at=r.created_at.isoformat(), is_builtin=False
    )


@router.put("/templates/{template_id}", dependencies=[Depends(require_role("editor"))])
def update_template(
    template_id: UUID, body: TemplateBodyIn, db: Session = Depends(get_db)
):
    """Update an existing export template."""
    r = (
        db.query(Ruleset)
        .filter(Ruleset.id == template_id, Ruleset.archived == False)
        .first()
    )
    if not r:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Template not found"
        )
    if r.is_builtin:
        raise HTTPException(
            status_code=403,
            detail="Cannot edit a built-in template \u2014 duplicate it first",
        )
    old_name = r.name
    config_dict = body.model_dump(exclude={"name"})
    r.config = config_dict
    r.name = body.name
    r.config_hash = hashlib.sha256(
        json.dumps(config_dict, sort_keys=True).encode()
    ).hexdigest()
    db.add(
        AuditLog(
            template_id=r.id,
            action="template_updated",
            old_value=old_name,
            new_value=r.name,
        )
    )
    db.commit()
    db.refresh(r)
    return TemplateOut(
        id=str(r.id),
        name=r.name,
        created_at=r.created_at.isoformat(),
        is_builtin=r.is_builtin,
    )


@router.delete(
    "/templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role("admin"))],
)
def delete_template(template_id: UUID, db: Session = Depends(get_db)):
    """Soft-delete an export template."""
    r = (
        db.query(Ruleset)
        .filter(Ruleset.id == template_id, Ruleset.archived == False)
        .first()
    )
    if not r:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Template not found"
        )
    if r.is_builtin:
        raise HTTPException(status_code=403, detail="Cannot delete a built-in template")
    r.archived = True
    db.add(
        AuditLog(
            template_id=r.id,
            action="template_deleted",
            old_value=r.name,
        )
    )
    db.commit()
    return None


@router.post(
    "/templates/{template_id}/duplicate",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role("editor"))],
)
def duplicate_template(template_id: UUID, db: Session = Depends(get_db)):
    """Clone a template under a new name."""
    r = db.query(Ruleset).filter(Ruleset.id == template_id).first()
    if not r:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Template not found"
        )
    new_r = Ruleset(
        name=f"Copy of {r.name}",
        config=dict(r.config),
        config_hash=r.config_hash,
        config_type="template",
        is_builtin=False,
    )
    db.add(new_r)
    db.flush()
    db.add(
        AuditLog(
            template_id=new_r.id,
            action="template_duplicated",
            old_value=r.name,
            new_value=new_r.name,
        )
    )
    db.commit()
    db.refresh(new_r)
    return TemplateOut(
        id=str(new_r.id),
        name=new_r.name,
        created_at=new_r.created_at.isoformat(),
        is_builtin=False,
    )
