"""Read-only routes for pre-reimport snapshots and the attributed before/after
diff of what an Update Import changed.

Snapshots are created automatically inside the re-import (see
``services/import_snapshot.py``); these endpoints expose them and the diff of a
snapshot against the current state. Mutating restore/undo is a separate change.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.models.import_model import Import
from backend.app.services.import_diff import diff_states
from backend.app.services.import_snapshot import (
    get_latest_snapshot,
    get_snapshot,
    list_snapshots,
    serialize_import_state,
)

router = APIRouter(tags=["snapshots"])


def _snapshot_meta(snap) -> dict:
    return {
        "id": str(snap.id),
        "kind": snap.kind,
        "note": snap.note,
        "created_at": snap.created_at.isoformat() if snap.created_at else None,
    }


def _require_import(import_id: UUID, db: Session) -> None:
    if not db.query(Import.id).filter(Import.id == import_id).first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import not found")


@router.get("/imports/{import_id}/snapshots")
def list_import_snapshots(import_id: UUID, db: Session = Depends(get_db)):
    """List pre-reimport snapshots for an import, newest first."""
    _require_import(import_id, db)
    return [_snapshot_meta(s) for s in list_snapshots(import_id, db)]


@router.get("/imports/{import_id}/reimport-diff")
def get_reimport_diff(import_id: UUID, db: Session = Depends(get_db)):
    """Attributed before/after diff of the most recent Update Import — the
    latest pre-reimport snapshot vs the current state."""
    _require_import(import_id, db)
    snap = get_latest_snapshot(import_id, db)
    if snap is None:
        return {"no_snapshot": True, "has_changes": False}
    current = serialize_import_state(import_id, db)
    return {
        "no_snapshot": False,
        "snapshot": _snapshot_meta(snap),
        **diff_states(snap.state, current),
    }


@router.get("/imports/{import_id}/snapshots/{snapshot_id}/diff")
def get_snapshot_diff(import_id: UUID, snapshot_id: UUID, db: Session = Depends(get_db)):
    """Diff a specific snapshot against the current state."""
    _require_import(import_id, db)
    snap = get_snapshot(snapshot_id, db)
    if snap is None or snap.import_id != import_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not found")
    current = serialize_import_state(import_id, db)
    return {
        "no_snapshot": False,
        "snapshot": _snapshot_meta(snap),
        **diff_states(snap.state, current),
    }
