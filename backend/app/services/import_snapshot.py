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

from backend.app.models.audit_log_model import AuditLog
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


# ---------------------------------------------------------------------------
# Restore (undo) — rebuild an import's state from a snapshot
# ---------------------------------------------------------------------------

# Server-managed timestamps are never restored explicitly — a restored row is
# genuinely (re-)created now.
_SKIP_COLS = {"created_at", "updated_at"}


def _coerce(col, val):
    """Coerce a JSON-decoded snapshot value back to the column's Python type
    (UUID string -> UUID, Decimal string -> Decimal); pass primitives through."""
    if val is None:
        return None
    try:
        pytype = col.type.python_type
    except (NotImplementedError, AttributeError):
        pytype = None
    if pytype is _uuid.UUID and isinstance(val, str):
        return _uuid.UUID(val)
    if pytype is Decimal and not isinstance(val, Decimal):
        return Decimal(str(val))
    return val


def _instance_from_dict(model, data: dict):
    """Rebuild an ORM instance from a serialised row dict, restoring every
    mapped column (so a new column can't silently drop out of restore) except
    server-managed timestamps."""
    kwargs = {
        col.name: _coerce(col, data[col.name])
        for col in model.__table__.columns
        if col.name not in _SKIP_COLS and col.name in data
    }
    return model(**kwargs)


def restore_snapshot(
    import_id: _uuid.UUID,
    snapshot: ImportSnapshot,
    db: Session,
    *,
    snapshot_current_first: bool = True,
) -> dict:
    """Replace an import's current state with the one captured in ``snapshot``.

    Wipes the import's current sections / works / overrides / validation
    warnings and rebuilds them verbatim from ``snapshot.state`` — restoring the
    original row ids so audit-log references stay valid, and the normalised
    values exactly as they were (no re-normalisation).

    Append-only and itself reversible: by default a ``pre_restore`` snapshot of
    the *current* state is captured first, so an unwanted restore can be undone
    too. Writes an audit-log entry. The caller commits.

    Returns counts: ``{"sections", "works", "overrides", "warnings"}``.
    """
    # Read everything we need off the snapshot up front: we expunge the session
    # below, which would detach it.
    state = snapshot.state or {}
    snapshot_created_iso = _iso(snapshot.created_at)

    # Capture the current state first so the restore is itself undoable.
    if snapshot_current_first:
        create_snapshot(
            import_id,
            db,
            kind="pre_restore",
            note=f"Before restoring snapshot taken {snapshot_created_iso}",
        )

    # Wipe current state (overrides -> warnings -> works -> sections).
    work_ids = [row.id for row in db.query(Work.id).filter(Work.import_id == import_id).all()]
    if work_ids:
        db.query(WorkOverride).filter(WorkOverride.work_id.in_(work_ids)).delete(
            synchronize_session=False
        )
    db.query(ValidationWarning).filter(ValidationWarning.import_id == import_id).delete(
        synchronize_session=False
    )
    db.query(Work).filter(Work.import_id == import_id).delete(synchronize_session=False)
    db.query(Section).filter(Section.import_id == import_id).delete(synchronize_session=False)
    db.flush()

    # Bulk deletes with synchronize_session=False leave stale instances in the
    # identity map; clear it so re-inserting rows with their original ids (for
    # audit continuity) can't collide with those ghosts.
    db.expunge_all()

    # Recreate sections first (FK targets), then works + overrides + warnings.
    counts = {"sections": 0, "works": 0, "overrides": 0, "warnings": 0}
    for sdict in state.get("sections", []):
        db.add(
            Section(
                id=_uuid.UUID(sdict["id"]),
                import_id=import_id,
                name=sdict["name"],
                position=sdict["position"],
            )
        )
        counts["sections"] += 1
    db.flush()

    for sdict in state.get("sections", []):
        for wdict in sdict.get("works", []):
            work = _instance_from_dict(Work, wdict)
            work.import_id = import_id  # belt-and-braces: pin to this import
            db.add(work)
            db.flush()  # work row must exist before its override/warnings (FK)
            counts["works"] += 1

            ovr = wdict.get("override")
            if ovr:
                override = _instance_from_dict(WorkOverride, ovr)
                override.work_id = work.id
                db.add(override)
                counts["overrides"] += 1

            for wn in wdict.get("warnings", []):
                db.add(
                    ValidationWarning(
                        import_id=import_id,
                        work_id=work.id,
                        warning_type=wn["warning_type"],
                        message=wn["message"],
                    )
                )
                counts["warnings"] += 1

    for iw in state.get("import_warnings", []):
        db.add(
            ValidationWarning(
                import_id=import_id,
                work_id=None,
                warning_type=iw["warning_type"],
                message=iw["message"],
            )
        )
        counts["warnings"] += 1

    db.add(
        AuditLog(
            import_id=import_id,
            work_id=None,
            action="snapshot_restore",
            field=None,
            old_value=None,
            new_value=(
                f"restored snapshot taken {snapshot_created_iso} "
                f"(sections={counts['sections']}, works={counts['works']}, "
                f"overrides={counts['overrides']})"
            ),
        )
    )

    return counts


def _iso(dt) -> str:
    return dt.isoformat() if dt is not None else "?"
