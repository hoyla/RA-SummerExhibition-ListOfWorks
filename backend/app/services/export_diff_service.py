"""
Export snapshot and diff service.

Snapshots the resolved export data on each export, and computes field-level
diffs between the current state and the last snapshot.

Covers both List of Works (LoW) and Artists' Index pipelines.
"""

from dataclasses import asdict
from sqlalchemy.orm import Session
from sqlalchemy import desc
from uuid import UUID
from typing import Optional

from backend.app.models.export_snapshot_model import ExportSnapshot
from backend.app.services.export_renderer import _collect_export_data


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


def save_export_snapshot(
    import_id: UUID,
    template_id: Optional[UUID],
    db: Session,
) -> ExportSnapshot:
    """Capture the current resolved export data and persist it."""
    data = _collect_export_data(import_id, db)
    snap = ExportSnapshot(
        import_id=import_id,
        template_id=template_id,
        snapshot_data=data,
    )
    db.add(snap)
    db.commit()
    db.refresh(snap)
    return snap


def get_last_snapshot(
    import_id: UUID,
    template_id: Optional[UUID],
    db: Session,
) -> Optional[ExportSnapshot]:
    """Return the most recent snapshot for an import+template pair."""
    q = db.query(ExportSnapshot).filter(ExportSnapshot.import_id == import_id)
    if template_id:
        q = q.filter(ExportSnapshot.template_id == template_id)
    else:
        q = q.filter(ExportSnapshot.template_id.is_(None))
    return q.order_by(desc(ExportSnapshot.exported_at)).first()


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------

# Fields we compare per work
_DIFF_FIELDS = [
    "number",
    "artist",
    "honorifics",
    "title",
    "price_numeric",
    "price_text",
    "edition_total",
    "edition_price_numeric",
    "artwork",
    "medium",
]


def _flatten_works(data: list[dict]) -> dict[str, dict]:
    """Turn section-grouped export data into a flat dict keyed by cat number.

    Returns {cat_no: {**work_fields, section_name, position_in_section}}.
    For works without a cat number, we use a synthetic key.
    """
    result = {}
    unnamed_counter = 0
    for section in data:
        for idx, work in enumerate(section.get("works", [])):
            key = work.get("number")
            if not key:
                unnamed_counter += 1
                key = f"__unnamed_{unnamed_counter}"
            # If duplicate, append position to disambiguate
            if key in result:
                key = f"{key}__pos{section['position']}_{idx}"
            work_copy = dict(work)
            work_copy["_section"] = section.get("section_name", "")
            result[key] = work_copy
    return result


def compute_diff(
    import_id: UUID,
    template_id: Optional[UUID],
    db: Session,
) -> dict:
    """Compare current export data against the last snapshot.

    Returns a dict with:
      - ``has_changes``: bool
      - ``previous_exported_at``: ISO timestamp or null
      - ``added``: list of works present now but not in snapshot
      - ``removed``: list of works in snapshot but not present now
      - ``changed``: list of works with field-level differences
      - ``unchanged_count``: int
    """
    snapshot = get_last_snapshot(import_id, template_id, db)

    if snapshot is None:
        # No previous export — nothing to compare against
        return {
            "has_changes": False,
            "previous_exported_at": None,
            "no_previous_export": True,
            "added": [],
            "removed": [],
            "changed": [],
            "unchanged_count": 0,
        }

    current_data = _collect_export_data(import_id, db)
    current_works = _flatten_works(current_data)

    old_works = _flatten_works(snapshot.snapshot_data)
    old_keys = set(old_works.keys())
    new_keys = set(current_works.keys())

    added_keys = new_keys - old_keys
    removed_keys = old_keys - new_keys
    common_keys = old_keys & new_keys

    added = [
        {
            "cat_no": k,
            "section": current_works[k]["_section"],
            **{f: current_works[k].get(f) for f in _DIFF_FIELDS},
        }
        for k in sorted(added_keys)
    ]
    removed = [
        {
            "cat_no": k,
            "section": old_works[k]["_section"],
            **{f: old_works[k].get(f) for f in _DIFF_FIELDS},
        }
        for k in sorted(removed_keys)
    ]

    changed = []
    unchanged_count = 0
    for k in sorted(common_keys):
        old_w = old_works[k]
        new_w = current_works[k]
        diffs = []
        for f in _DIFF_FIELDS:
            old_val = old_w.get(f)
            new_val = new_w.get(f)
            if old_val != new_val:
                diffs.append({"field": f, "old": old_val, "new": new_val})
        # Also check section change
        if old_w.get("_section") != new_w.get("_section"):
            diffs.append(
                {
                    "field": "section",
                    "old": old_w.get("_section"),
                    "new": new_w.get("_section"),
                }
            )

        if diffs:
            changed.append(
                {
                    "cat_no": k,
                    "section": new_w["_section"],
                    "fields": diffs,
                }
            )
        else:
            unchanged_count += 1

    return {
        "has_changes": bool(added or removed or changed),
        "previous_exported_at": snapshot.exported_at.isoformat(),
        "added": added,
        "removed": removed,
        "changed": changed,
        "unchanged_count": unchanged_count,
    }


# ===================================================================
# Artists' Index — snapshot & diff
# ===================================================================


def _collect_index_export_data(import_id: UUID, db: Session) -> list[dict]:
    """Collect index entries and serialise them to plain dicts for JSONB storage."""
    from backend.app.services.index_renderer import collect_index_entries

    entries = collect_index_entries(db, import_id)
    return [asdict(e) for e in entries]


def save_index_export_snapshot(
    import_id: UUID,
    template_id: Optional[UUID],
    db: Session,
) -> ExportSnapshot:
    """Capture the current resolved index data and persist it."""
    data = _collect_index_export_data(import_id, db)
    snap = ExportSnapshot(
        import_id=import_id,
        template_id=template_id,
        snapshot_data=data,
    )
    db.add(snap)
    db.commit()
    db.refresh(snap)
    return snap


# Fields compared per index entry
_INDEX_DIFF_FIELDS = [
    "title",
    "first_name",
    "last_name",
    "quals",
    "company",
    "second_artist",
    "is_ra_member",
    "is_company",
    "cat_nos",
]


def _entry_key(entry: dict) -> str:
    """Deterministic key for an index entry.

    Uses sort_key + courtesy so that the same artist with different courtesy
    groups gets separate keys.
    """
    courtesy = entry.get("courtesy") or ""
    return f'{entry.get("sort_key", "")}::{courtesy}'


def _entry_display_name(entry: dict) -> str:
    """Human-readable label for an index entry, e.g. 'SMITH, John RA'."""
    parts = []
    if entry.get("last_name"):
        parts.append(entry["last_name"].upper())
    if entry.get("first_name"):
        parts.append(entry["first_name"])
    name = ", ".join(parts) if parts else "(unknown)"
    if entry.get("quals"):
        name += f' {entry["quals"]}'
    return name


def _flatten_index_entries(data: list[dict]) -> dict[str, dict]:
    """Turn a list of serialised index entries into a dict keyed by entry_key."""
    result = {}
    counter = 0
    for entry in data:
        key = _entry_key(entry)
        if key in result:
            counter += 1
            key = f"{key}__dup{counter}"
        result[key] = entry
    return result


def compute_index_diff(
    import_id: UUID,
    template_id: Optional[UUID],
    db: Session,
) -> dict:
    """Compare current index data against the last snapshot.

    Returns a dict with:
      - ``has_changes``: bool
      - ``previous_exported_at``: ISO timestamp or null
      - ``added``: list of entries present now but not in snapshot
      - ``removed``: list of entries in snapshot but not present now
      - ``changed``: list of entries with field-level differences
      - ``unchanged_count``: int
    """
    snapshot = get_last_snapshot(import_id, template_id, db)

    if snapshot is None:
        return {
            "has_changes": False,
            "previous_exported_at": None,
            "no_previous_export": True,
            "added": [],
            "removed": [],
            "changed": [],
            "unchanged_count": 0,
        }

    current_data = _collect_index_export_data(import_id, db)
    current_entries = _flatten_index_entries(current_data)
    old_entries = _flatten_index_entries(snapshot.snapshot_data)

    old_keys = set(old_entries.keys())
    new_keys = set(current_entries.keys())

    added_keys = new_keys - old_keys
    removed_keys = old_keys - new_keys
    common_keys = old_keys & new_keys

    added = [
        {
            "name": _entry_display_name(current_entries[k]),
            "courtesy": current_entries[k].get("courtesy"),
            "cat_nos": current_entries[k].get("cat_nos", []),
        }
        for k in sorted(added_keys)
    ]
    removed = [
        {
            "name": _entry_display_name(old_entries[k]),
            "courtesy": old_entries[k].get("courtesy"),
            "cat_nos": old_entries[k].get("cat_nos", []),
        }
        for k in sorted(removed_keys)
    ]

    changed = []
    unchanged_count = 0
    for k in sorted(common_keys):
        old_e = old_entries[k]
        new_e = current_entries[k]
        diffs = []
        for f in _INDEX_DIFF_FIELDS:
            old_val = old_e.get(f)
            new_val = new_e.get(f)
            if old_val != new_val:
                diffs.append({"field": f, "old": old_val, "new": new_val})

        if diffs:
            changed.append(
                {
                    "name": _entry_display_name(new_e),
                    "courtesy": new_e.get("courtesy"),
                    "fields": diffs,
                }
            )
        else:
            unchanged_count += 1

    return {
        "has_changes": bool(added or removed or changed),
        "previous_exported_at": snapshot.exported_at.isoformat(),
        "added": added,
        "removed": removed,
        "changed": changed,
        "unchanged_count": unchanged_count,
    }
