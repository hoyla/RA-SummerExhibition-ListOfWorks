"""Pre-reimport snapshots of an import's full mutable state.

A snapshot is captured automatically just before a re-import rewrites the
works/overrides, so the team can see an after-the-fact before/after diff of
what an Update Import changed — and why (source vs normalisation vs override) —
and, if needed, restore the prior state wholesale.

Append-only: each re-import adds a row; nothing is mutated in place. This
mirrors the export-snapshot / low-tag-snapshot pattern already in the codebase
and the project's defensibility principle (every aggregate claim drillable back
to the underlying source state).

The serialised ``state`` stores *every* column of each Work and WorkOverride
row (not a hand-maintained subset), so a newly-added field can never silently
fall out of the snapshot the way override fields fell out of reimport
preservation. Decimal values are stored as strings to preserve precision.
"""

from __future__ import annotations

import uuid as _uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from backend.app.models.import_snapshot_model import ImportSnapshot
from backend.app.models.override_model import WorkOverride
from backend.app.models.section_model import Section
from backend.app.models.validation_warning_model import ValidationWarning
from backend.app.models.work_model import Work

# Bump when the on-disk shape of ``state`` changes in a non-additive way.
STATE_VERSION = 1


def _col_to_json(value):
    """Convert a single SQLAlchemy column value to a JSON-safe primitive.

    Decimal -> str (never float) so monetary precision survives the round-trip;
    UUID/datetime -> str; primitives pass through unchanged.
    """
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, _uuid.UUID):
        return str(value)
    return str(value)


def _row_to_dict(obj) -> dict:
    """Serialise every mapped column of an ORM row to a JSON-safe dict."""
    return {c.name: _col_to_json(getattr(obj, c.name)) for c in obj.__table__.columns}


def serialize_import_state(import_id: _uuid.UUID, db: Session) -> dict:
    """Build the full mutable-state tree for an import.

    Structure::

        {
          "version": 1,
          "sections": [
            {"id", "name", "position",
             "works": [
               {<all Work columns>,
                "override": {<all WorkOverride columns>} | None,
                "warnings": [{"warning_type", "message"}, ...]}
             ]}
          ],
          "import_warnings": [{"warning_type", "message"}, ...]   # work_id IS NULL
        }

    Works are grouped under their section and ordered by
    ``position_in_section``; sections are ordered by ``position`` — so the
    snapshot preserves document order for both diffing and restore.
    """
    sections = (
        db.query(Section).filter(Section.import_id == import_id).order_by(Section.position).all()
    )
    works = db.query(Work).filter(Work.import_id == import_id).all()
    work_ids = [w.id for w in works]

    overrides_by_work: dict = {}
    if work_ids:
        overrides_by_work = {
            o.work_id: o
            for o in db.query(WorkOverride).filter(WorkOverride.work_id.in_(work_ids)).all()
        }

    # Validation warnings: split into per-work and import-level (work_id NULL).
    warnings_by_work: dict = {}
    import_warnings: list = []
    for w in db.query(ValidationWarning).filter(ValidationWarning.import_id == import_id).all():
        entry = {"warning_type": w.warning_type, "message": w.message}
        if w.work_id is None:
            import_warnings.append(entry)
        else:
            warnings_by_work.setdefault(w.work_id, []).append(entry)

    works_by_section: dict = {}
    for w in works:
        works_by_section.setdefault(w.section_id, []).append(w)
    for lst in works_by_section.values():
        lst.sort(key=lambda x: x.position_in_section)

    section_dicts = []
    for s in sections:
        work_dicts = []
        for w in works_by_section.get(s.id, []):
            wd = _row_to_dict(w)
            ovr = overrides_by_work.get(w.id)
            wd["override"] = _row_to_dict(ovr) if ovr else None
            wd["warnings"] = warnings_by_work.get(w.id, [])
            work_dicts.append(wd)
        section_dicts.append(
            {
                "id": str(s.id),
                "name": s.name,
                "position": s.position,
                "works": work_dicts,
            }
        )

    return {
        "version": STATE_VERSION,
        "sections": section_dicts,
        "import_warnings": import_warnings,
    }


def list_snapshots(import_id: _uuid.UUID, db: Session) -> list[ImportSnapshot]:
    """All snapshots for an import, newest first."""
    return (
        db.query(ImportSnapshot)
        .filter(ImportSnapshot.import_id == import_id)
        .order_by(ImportSnapshot.created_at.desc())
        .all()
    )


def get_latest_snapshot(import_id: _uuid.UUID, db: Session) -> Optional[ImportSnapshot]:
    """The most recent snapshot for an import, or None."""
    return (
        db.query(ImportSnapshot)
        .filter(ImportSnapshot.import_id == import_id)
        .order_by(ImportSnapshot.created_at.desc())
        .first()
    )


def get_snapshot(snapshot_id: _uuid.UUID, db: Session) -> Optional[ImportSnapshot]:
    """A snapshot by id, or None."""
    return db.query(ImportSnapshot).filter(ImportSnapshot.id == snapshot_id).first()


def create_snapshot(
    import_id: _uuid.UUID,
    db: Session,
    *,
    kind: str = "pre_reimport",
    note: Optional[str] = None,
) -> ImportSnapshot:
    """Capture and persist the current full mutable state of an import.

    The caller owns the surrounding transaction: this adds and flushes the row
    but does **not** commit, so the snapshot participates in the re-import's
    atomic unit — if the re-import rolls back, the snapshot is discarded too.
    """
    snap = ImportSnapshot(
        import_id=import_id,
        kind=kind,
        note=note,
        state=serialize_import_state(import_id, db),
    )
    db.add(snap)
    db.flush()
    return snap
