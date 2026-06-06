"""Attributed before/after diff between two List-of-Works import states.

Given two serialised import states (see ``import_snapshot.serialize_import_state``),
pair their works and report, for each matched pair, the field-level changes —
each attributed to *why* it changed:

  - ``source``        : the raw spreadsheet value changed
  - ``normalisation`` : raw identical, but the normalised value changed
                        (i.e. the normalisation rules drifted between the two states)
  - ``override``      : the editorial override changed

This is the generalisable core. The re-import diff feeds (pre-reimport snapshot,
current state); a future "compare two imports" tool feeds two live import states.
Both call :func:`diff_states`.

Pairing vs. the re-import matcher
---------------------------------
This shares the *fingerprint primitive* with ``reimport_matcher`` but inverts the
pass order, because a diff's goal is the opposite of override preservation's.

``reimport_matcher`` pairs **cat-no first, gated on fingerprint** — deliberately
conservative, so an override is never transplanted onto changed content.

A diff wants to *surface* changes, so it pairs **fingerprint first** (same
content, even if renumbered — catches renumbers and unchanged works), then
**catalogue number** for the remainder (same slot, edited content — catches a
typo fix that the conservative matcher would otherwise show as a remove + add).
What neither pass can confidently pair becomes added / removed.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from backend.app.services.override_service import resolve_effective_work
from backend.app.services.reimport_matcher import compute_fingerprint


@dataclass(frozen=True)
class _FieldSpec:
    """One resolved (export-facing) field and the columns used to attribute a
    change in it to source / normalisation / override."""

    name: str  # EffectiveWork attribute and output key
    norm_col: str  # Work column holding the normalised (pre-override) value
    raw_cols: tuple  # raw Work columns that feed it (source attribution)
    override_cols: tuple  # WorkOverride columns that can drive it


# Resolved fields compared per matched work, in display order. ``include_in_export``
# is handled separately (it's a flag, not a resolved value with raw/override layers).
_FIELDS = [
    _FieldSpec("title", "title", ("raw_title",), ("title_override",)),
    _FieldSpec("title_cased", "title_cased", ("raw_title",), ("title_cased_override",)),
    _FieldSpec("artist_name", "artist_name", ("raw_artist",), ("artist_name_override",)),
    _FieldSpec(
        "artist_honorifics",
        "artist_honorifics",
        ("raw_artist",),
        ("artist_honorifics_override",),
    ),
    # price_text can suppress price_numeric, so both override cols attribute a numeric change.
    _FieldSpec(
        "price_numeric",
        "price_numeric",
        ("raw_price",),
        ("price_numeric_override", "price_text_override"),
    ),
    _FieldSpec("price_text", "price_text", ("raw_price",), ("price_text_override",)),
    _FieldSpec("edition_total", "edition_total", ("raw_edition",), ("edition_total_override",)),
    _FieldSpec(
        "edition_price_numeric",
        "edition_price_numeric",
        ("raw_edition",),
        ("edition_price_numeric_override",),
    ),
    _FieldSpec("artwork", "artwork", ("raw_artwork",), ("artwork_override",)),
    _FieldSpec("medium", "medium", ("raw_medium",), ("medium_override",)),
]


def _flatten(state: dict) -> list[dict]:
    """Flatten a state's sections into a list of work dicts, tagging each with
    its section name under ``_section``."""
    works = []
    for section in state.get("sections", []):
        for w in section.get("works", []):
            wd = dict(w)
            wd["_section"] = section.get("name", "")
            works.append(wd)
    return works


def _effective(work: dict):
    """Resolve a serialised work dict (normalised columns + optional override)
    to its export-facing values, reusing the production resolver."""
    work_obj = SimpleNamespace(
        **{k: v for k, v in work.items() if k not in ("override", "warnings")}
    )
    ovr = work.get("override")
    override_obj = SimpleNamespace(**ovr) if ovr else None
    return resolve_effective_work(work_obj, override_obj)


def _summary(work: dict) -> dict:
    """Compact identifier for a work in the diff output."""
    eff = _effective(work)
    return {
        "cat_no": work.get("raw_cat_no"),
        "section": work.get("_section"),
        "title": eff.title,
        "artist": eff.artist_name,
    }


def _cat_key(work: dict) -> str:
    raw = work.get("raw_cat_no")
    return str(raw).strip() if raw is not None else ""


def _fp_key(work: dict):
    return compute_fingerprint(
        work.get("raw_title"), work.get("raw_artist"), work.get("raw_medium")
    )


def _pair_works(old_works: list[dict], new_works: list[dict]):
    """Pair old↔new works for diffing.

    Pass 1 — **fingerprint** (content identity): pairs unchanged and renumbered
    works. Pass 2 — **catalogue number** on the remainder: pairs same-slot works
    whose content was edited. Greedy one-to-one within each key bucket; whatever
    is left over is added / removed.

    Returns ``(pairs, added, removed)`` where ``pairs`` is a list of
    ``(old, new, via)`` and ``via`` is ``"fingerprint"`` or ``"cat_no"``.
    """
    consumed_new: set = set()
    pairs: list[tuple] = []

    # Pass 1: fingerprint
    new_by_fp: dict = {}
    for w in new_works:
        new_by_fp.setdefault(_fp_key(w), []).append(w)
    remaining_old: list[dict] = []
    for ow in old_works:
        nw = next((w for w in new_by_fp.get(_fp_key(ow), []) if w["id"] not in consumed_new), None)
        if nw is not None:
            consumed_new.add(nw["id"])
            pairs.append((ow, nw, "fingerprint"))
        else:
            remaining_old.append(ow)

    # Pass 2: catalogue number (non-empty only)
    new_by_cat: dict = {}
    for w in new_works:
        k = _cat_key(w)
        if k:
            new_by_cat.setdefault(k, []).append(w)
    removed: list[dict] = []
    for ow in remaining_old:
        k = _cat_key(ow)
        nw = (
            next((w for w in new_by_cat.get(k, []) if w["id"] not in consumed_new), None)
            if k
            else None
        )
        if nw is not None:
            consumed_new.add(nw["id"])
            pairs.append((ow, nw, "cat_no"))
        else:
            removed.append(ow)

    added = [w for w in new_works if w["id"] not in consumed_new]
    return pairs, added, removed


def _field_changes(old: dict, new: dict) -> list[dict]:
    """Field-level attributed changes between a matched old/new work pair."""
    old_eff, new_eff = _effective(old), _effective(new)
    old_ovr = old.get("override") or {}
    new_ovr = new.get("override") or {}

    changes: list[dict] = []

    # Catalogue number can change without a content change (a renumber); the
    # spreadsheet is the source of truth for it, so attribute to source.
    if _cat_key(old) != _cat_key(new):
        changes.append(
            {
                "field": "cat_no",
                "old": old.get("raw_cat_no"),
                "new": new.get("raw_cat_no"),
                "causes": ["source"],
            }
        )

    for spec in _FIELDS:
        old_val = getattr(old_eff, spec.name)
        new_val = getattr(new_eff, spec.name)
        if old_val == new_val:
            continue

        causes: list[str] = []
        if any(old_ovr.get(c) != new_ovr.get(c) for c in spec.override_cols):
            causes.append("override")
        if any(old.get(c) != new.get(c) for c in spec.raw_cols):
            causes.append("source")
        elif old.get(spec.norm_col) != new.get(spec.norm_col):
            # Raw identical but the normalised value moved → rules drifted.
            causes.append("normalisation")

        changes.append(
            {
                "field": spec.name,
                "old": old_val,
                "new": new_val,
                # Resolved value changed, so at least one layer must have moved;
                # "unknown" is a defensive fallback that shouldn't occur.
                "causes": causes or ["unknown"],
            }
        )

    if bool(old.get("include_in_export")) != bool(new.get("include_in_export")):
        changes.append(
            {
                "field": "include_in_export",
                "old": bool(old.get("include_in_export")),
                "new": bool(new.get("include_in_export")),
                "causes": ["override"],
            }
        )

    if old.get("_section") != new.get("_section"):
        changes.append(
            {
                "field": "section",
                "old": old.get("_section"),
                "new": new.get("_section"),
                "causes": ["source"],
            }
        )

    return changes


def diff_states(old_state: dict, new_state: dict) -> dict:
    """Compute the attributed before/after diff between two import states.

    Returns::

        {
          "has_changes": bool,
          "changed": [{"old": <summary>, "new": <summary>, "via": "fingerprint"|"cat_no",
                       "fields": [{"field", "old", "new", "causes": [...]}, ...]}, ...],
          "added":   [<summary>, ...],   # in new but not paired to any old work
          "removed": [<summary>, ...],   # in old but not paired to any new work
          "unchanged_count": int,
          "counts": {"changed", "added", "removed", "unchanged"},
        }
    """
    old_works = _flatten(old_state)
    new_works = _flatten(new_state)

    pairs, added_works, removed_works = _pair_works(old_works, new_works)

    changed: list[dict] = []
    unchanged = 0
    for old_w, new_w, via in pairs:
        fields = _field_changes(old_w, new_w)
        if fields:
            changed.append(
                {"old": _summary(old_w), "new": _summary(new_w), "via": via, "fields": fields}
            )
        else:
            unchanged += 1

    added = [_summary(w) for w in added_works]
    removed = [_summary(w) for w in removed_works]

    return {
        "has_changes": bool(changed or added or removed),
        "changed": changed,
        "added": added,
        "removed": removed,
        "unchanged_count": unchanged,
        "counts": {
            "changed": len(changed),
            "added": len(added),
            "removed": len(removed),
            "unchanged": unchanged,
        },
    }
