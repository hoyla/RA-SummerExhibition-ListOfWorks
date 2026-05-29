"""Plan a re-import: match preserved overrides from the old DB state against
rows in a freshly-uploaded spreadsheet, without committing anything.

This module is **pure** — no DB session, no I/O. It takes the old and new sides
as plain dataclasses and returns a ``MatchPlan`` describing what would happen
if the re-import were committed. The importer wraps it with the DB read/write
side; the API exposes ``dry_run`` so the plan can be returned to the user as
a preview before any mutation.

Why this exists
---------------
The pre-existing re-import matches preserved overrides to new works **purely
by catalogue number** (``raw_cat_no``). That breaks in two distinct ways when
the gallery inserts a work and renumbers everything after it:

1. **Lost overrides on renumbered works.** Old work 1700's override is keyed
   to cat 1700; the new spreadsheet's work-with-the-same-content is now at
   cat 1701; the override doesn't get restored.

2. **Silent misapplication.** Worse — the new cat 1700 is *different* content
   (was old cat 1699). The old override gets restored onto it without warning.
   An overridden price, an ``exclude_in_export`` flag, or editor notes are
   silently transplanted onto the wrong work.

The matcher fixes both by adding a **content fingerprint** as a secondary
join key. When cat-no matches and the fingerprint also agrees → strong
match. When cat-no matches but fingerprints differ → suspected renumber
collision, *don't* restore; let the second pass try to find the work
elsewhere. When fingerprint matches some new row with a different cat-no →
fingerprint match (the renumber case, handled). Unmatched preserved
overrides are reported with their identifying fields so the user knows what
to review.

Scope filter
------------
The matcher also accepts a ``gallery_scope`` — when set, only old works in
those galleries are considered "at risk", and only new rows in those
galleries are considered targets. This supports the selective re-import flow
(re-import only the last three galleries, leave the rest untouched in the
DB). Cross-gallery moves into / out of the scope are detected and reported
as warnings — they're the one shape selective re-import can't handle
cleanly, and the user needs to either expand the scope or accept that those
works will be duplicated / lost.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------


Fingerprint = tuple[str, str, str]
"""Normalised (title, artist, medium) — the content fingerprint of a work."""


def _norm(value: Optional[str]) -> str:
    """Normalise a single fingerprint component for comparison.

    NFKC-normalise (collapses width / compatibility variants), strip + lower
    + collapse internal whitespace. Punctuation is *kept* — the same artist's
    "Untitled (after dusk)" and "Untitled after dusk" should not collide.
    Empty / None → empty string so a missing medium can still fingerprint
    cleanly against a missing medium.
    """
    if not value:
        return ""
    s = unicodedata.normalize("NFKC", str(value)).strip().lower()
    return re.sub(r"\s+", " ", s)


def compute_fingerprint(
    title: Optional[str],
    artist: Optional[str],
    medium: Optional[str],
) -> Fingerprint:
    """Build a fingerprint from the three fields used for content identity.

    These three pin a work tightly enough for the catalogue: title alone has
    a non-trivial collision rate ("Untitled", "Self-Portrait", etc.) and
    artist alone is rarely unique for a prolific exhibitor; the three
    together collide vanishingly rarely. Cat number is the obvious fourth
    candidate but that's the very field the matcher is trying to be robust
    against.
    """
    return (_norm(title), _norm(artist), _norm(medium))


def _weak_fingerprint(fp: Fingerprint) -> tuple[str, str]:
    """Title + artist only — used as a tertiary fallback when the medium has
    been edited (a common editorial correction). Returned as a separate
    function so callers can opt in to weaker matching explicitly."""
    return (fp[0], fp[1])


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OldWorkSnapshot:
    """One existing work in the DB, with the data the matcher needs to decide
    whether and how to preserve its override."""

    cat_no: str  # str-normalised (whitespace-stripped) — empty string if none
    gallery: str  # ``raw_gallery`` for scope filtering, "" if missing
    fingerprint: Fingerprint
    include_in_export: bool
    override: Optional[dict] = None  # field-name → value dict, or None for no override
    # Identifying fields for the human-readable plan output:
    raw_title: Optional[str] = None
    raw_artist: Optional[str] = None


@dataclass(frozen=True)
class NewWorkRow:
    """One parsed row from the freshly-uploaded spreadsheet."""

    cat_no: str  # str-normalised — empty string if blank
    gallery: str
    fingerprint: Fingerprint
    # Identifying fields for the human-readable plan output:
    raw_title: Optional[str] = None
    raw_artist: Optional[str] = None


# ---------------------------------------------------------------------------
# Plan output
# ---------------------------------------------------------------------------


@dataclass
class MatchedItem:
    """One preserved override that will be restored onto a new work."""

    old_cat_no: str
    new_cat_no: str
    new_row_index: int  # 0-based position in the input new_rows list
    via: str  # "cat_no" | "fingerprint"
    raw_title: Optional[str]
    raw_artist: Optional[str]
    had_override: bool  # False if only include_in_export was non-default


@dataclass
class UnmatchedItem:
    """A preserved override with no acceptable target in the new spreadsheet.
    Its override will be lost unless the user expands the gallery scope or
    re-applies manually."""

    old_cat_no: str
    raw_title: Optional[str]
    raw_artist: Optional[str]
    had_override: bool
    reason: str  # "no_fingerprint_match" | "cat_no_collision_no_fingerprint_match"


@dataclass
class AmbiguousItem:
    """A preserved override that could match more than one new row by
    fingerprint, or a cat-no match where the fingerprint disagreed. The
    matcher refuses to guess; the user must resolve manually."""

    old_cat_no: str
    raw_title: Optional[str]
    raw_artist: Optional[str]
    candidate_new_cat_nos: list[str]
    reason: str  # "fingerprint_collision" | "cat_no_match_fingerprint_mismatch"


@dataclass
class CrossGalleryMoveWarning:
    """A new-spreadsheet row inside the selected gallery scope appears
    (by fingerprint) to be a work that's currently in a gallery *outside*
    the scope. Selective re-import would duplicate it: the old copy stays
    in its current gallery (untouched), and a new copy appears in the
    selected gallery. The user should extend the scope to include both, or
    delete the old copy manually."""

    new_cat_no: str
    raw_title: Optional[str]
    raw_artist: Optional[str]
    old_cat_no: str
    old_gallery: str
    new_gallery: str


@dataclass
class GallerySummary:
    """One gallery in the new spreadsheet, with the metadata the UI needs
    for the picker."""

    name: str
    position: int  # 1-based order in the new spreadsheet
    work_count: int
    cat_no_min: Optional[int]  # None when no numeric cat_nos
    cat_no_max: Optional[int]
    in_scope: bool


@dataclass
class MatchPlan:
    """The full plan computed by ``match_overrides``. Serialisable to JSON
    for the dry-run API response and the UI."""

    matched: list[MatchedItem] = field(default_factory=list)
    unmatched: list[UnmatchedItem] = field(default_factory=list)
    ambiguous: list[AmbiguousItem] = field(default_factory=list)
    cross_gallery_warnings: list[CrossGalleryMoveWarning] = field(default_factory=list)
    galleries: list[GallerySummary] = field(default_factory=list)
    # Bulk counts (derived, but precomputed for convenience in the response):
    matched_by_cat_no: int = 0
    matched_by_fingerprint: int = 0
    added: int = 0  # new rows with no preserved match
    removed: int = 0  # preserved entries with no match in new rows
    overrides_preserved: int = 0  # subset of matched that had a real override
    overrides_at_risk: int = 0  # subset of unmatched + ambiguous that had a real override


# ---------------------------------------------------------------------------
# Matcher
# ---------------------------------------------------------------------------


def match_overrides(
    old: list[OldWorkSnapshot],
    new: list[NewWorkRow],
    *,
    gallery_scope: Optional[set[str]] = None,
) -> MatchPlan:
    """Compute the override-preservation plan for a re-import.

    Pure function: no I/O. Given the old DB state and the new spreadsheet
    rows, returns a ``MatchPlan`` describing which overrides would be
    preserved (and via which mechanism), which would be lost, and which
    require human disambiguation.

    Algorithm
    ---------
    Two passes. The first preserves the historical "match by cat_no"
    behaviour for the common case — but *only* when the fingerprint also
    agrees, closing today's silent-misapplication bug. The second covers the
    renumber case by matching on fingerprint alone.

    1. **Cat-no pass.** For each preserved entry, look for a new row with
       the same cat_no. If found and fingerprints agree, mark matched. If
       fingerprints differ → ambiguous (cat-no collision, content mismatch).
       Old works outside ``gallery_scope`` are skipped entirely; the entry
       is dropped from ``preserve`` before this pass so it can't even be
       considered.
    2. **Fingerprint pass.** For each preserved entry not yet matched (and
       still in scope), look for unmatched new rows with the same fingerprint
       in scope. Exactly one → fingerprint match. More than one → ambiguous.
       Zero → unmatched (override will be lost unless re-applied).

    Cross-gallery moves are detected as a side effect of the fingerprint
    pass: if a new in-scope row's fingerprint matches an old work that's in
    a non-scope gallery, that's a warning (user should extend the scope).

    Gallery summary (for the UI picker) is computed up front from the new
    spreadsheet alone.
    """
    plan = MatchPlan()

    # ------------------------------------------------------------------
    # 0. Gallery summary — drives the UI picker independently of matching
    # ------------------------------------------------------------------
    plan.galleries = _build_gallery_summary(new, gallery_scope)

    # ------------------------------------------------------------------
    # Scope filtering: split old into in-scope / out-of-scope, and the
    # new rows similarly. Out-of-scope new rows are ignored (they belong
    # to galleries the user hasn't selected for re-import and don't appear
    # in the new spreadsheet's scope). Out-of-scope old works keep their
    # current state regardless — the matcher must not claim them as
    # "removed" or otherwise act on them.
    # ------------------------------------------------------------------
    if gallery_scope is None:
        in_scope_old = list(old)
        in_scope_new = list(new)
        out_of_scope_old = []
    else:
        in_scope_old = [w for w in old if w.gallery in gallery_scope]
        out_of_scope_old = [w for w in old if w.gallery not in gallery_scope]
        in_scope_new = [r for r in new if r.gallery in gallery_scope]

    # Index new rows by cat_no and fingerprint for fast lookup. ``new_by_cat``
    # holds the first row per cat_no (duplicate cat_nos are a separate
    # importer warning); ``new_by_fp`` is fingerprint → list of indices into
    # ``in_scope_new`` (the matcher needs to know about collisions).
    new_by_cat: dict[str, int] = {}
    new_by_fp: dict[Fingerprint, list[int]] = {}
    for i, row in enumerate(in_scope_new):
        if row.cat_no and row.cat_no not in new_by_cat:
            new_by_cat[row.cat_no] = i
        new_by_fp.setdefault(row.fingerprint, []).append(i)

    matched_new_indices: set[int] = set()

    # ------------------------------------------------------------------
    # Pass 1: cat-no match, gated on fingerprint agreement
    # ------------------------------------------------------------------
    pending_old: list[OldWorkSnapshot] = []  # entries to retry in pass 2
    for old_w in in_scope_old:
        if not old_w.cat_no:
            pending_old.append(old_w)
            continue
        new_idx = new_by_cat.get(old_w.cat_no)
        if new_idx is None:
            pending_old.append(old_w)
            continue
        new_row = in_scope_new[new_idx]
        if new_row.fingerprint == old_w.fingerprint:
            # Strong match — same cat_no AND same content
            matched_new_indices.add(new_idx)
            plan.matched.append(
                MatchedItem(
                    old_cat_no=old_w.cat_no,
                    new_cat_no=new_row.cat_no,
                    new_row_index=new_idx,
                    via="cat_no",
                    raw_title=old_w.raw_title,
                    raw_artist=old_w.raw_artist,
                    had_override=bool(old_w.override),
                )
            )
            plan.matched_by_cat_no += 1
            if old_w.override:
                plan.overrides_preserved += 1
            continue
        # Cat-no matches but content differs — this is exactly the case
        # the historical bug fired on. Don't restore; defer to pass 2 in
        # case the same content appears at a different cat_no. The
        # collision itself becomes an ambiguous-item warning IF pass 2
        # doesn't find a unique fingerprint match.
        pending_old.append(old_w)

    # ------------------------------------------------------------------
    # Pass 2: fingerprint fallback for everything still unmatched
    # ------------------------------------------------------------------
    for old_w in pending_old:
        # Try the strong (3-field) fingerprint first
        candidates = [
            i for i in new_by_fp.get(old_w.fingerprint, []) if i not in matched_new_indices
        ]
        if len(candidates) == 1:
            new_idx = candidates[0]
            new_row = in_scope_new[new_idx]
            matched_new_indices.add(new_idx)
            plan.matched.append(
                MatchedItem(
                    old_cat_no=old_w.cat_no,
                    new_cat_no=new_row.cat_no,
                    new_row_index=new_idx,
                    via="fingerprint",
                    raw_title=old_w.raw_title,
                    raw_artist=old_w.raw_artist,
                    had_override=bool(old_w.override),
                )
            )
            plan.matched_by_fingerprint += 1
            if old_w.override:
                plan.overrides_preserved += 1
            continue

        if len(candidates) > 1:
            plan.ambiguous.append(
                AmbiguousItem(
                    old_cat_no=old_w.cat_no,
                    raw_title=old_w.raw_title,
                    raw_artist=old_w.raw_artist,
                    candidate_new_cat_nos=[in_scope_new[i].cat_no for i in candidates],
                    reason="fingerprint_collision",
                )
            )
            if old_w.override:
                plan.overrides_at_risk += 1
            continue

        # No fingerprint match. If the cat-no was occupied by a content
        # mismatch in pass 1, surface that specifically — it's a different
        # signal than "the work just isn't in the new file at all".
        cat_collision_new_idx = new_by_cat.get(old_w.cat_no) if old_w.cat_no else None
        if cat_collision_new_idx is not None and cat_collision_new_idx not in matched_new_indices:
            collision_row = in_scope_new[cat_collision_new_idx]
            plan.ambiguous.append(
                AmbiguousItem(
                    old_cat_no=old_w.cat_no,
                    raw_title=old_w.raw_title,
                    raw_artist=old_w.raw_artist,
                    candidate_new_cat_nos=[collision_row.cat_no],
                    reason="cat_no_match_fingerprint_mismatch",
                )
            )
            if old_w.override:
                plan.overrides_at_risk += 1
            continue

        plan.unmatched.append(
            UnmatchedItem(
                old_cat_no=old_w.cat_no,
                raw_title=old_w.raw_title,
                raw_artist=old_w.raw_artist,
                had_override=bool(old_w.override),
                reason="no_fingerprint_match",
            )
        )
        if old_w.override:
            plan.overrides_at_risk += 1

    # ------------------------------------------------------------------
    # Cross-gallery move detection (scope-only). For any new in-scope row
    # whose fingerprint matches an old work in a non-scope gallery, warn.
    # If we didn't warn, the importer would create a new work in the
    # selected gallery while the old work stayed put outside the scope —
    # silent duplication.
    # ------------------------------------------------------------------
    if gallery_scope is not None:
        out_of_scope_by_fp: dict[Fingerprint, OldWorkSnapshot] = {}
        for w in out_of_scope_old:
            out_of_scope_by_fp.setdefault(w.fingerprint, w)
        for i, row in enumerate(in_scope_new):
            old_w = out_of_scope_by_fp.get(row.fingerprint)
            if old_w is None:
                continue
            plan.cross_gallery_warnings.append(
                CrossGalleryMoveWarning(
                    new_cat_no=row.cat_no,
                    raw_title=row.raw_title,
                    raw_artist=row.raw_artist,
                    old_cat_no=old_w.cat_no,
                    old_gallery=old_w.gallery,
                    new_gallery=row.gallery,
                )
            )

    # ------------------------------------------------------------------
    # Derived counts
    # ------------------------------------------------------------------
    plan.added = len(in_scope_new) - len(matched_new_indices)
    plan.removed = len(in_scope_old) - plan.matched_by_cat_no - plan.matched_by_fingerprint

    return plan


def _build_gallery_summary(
    new: list[NewWorkRow],
    gallery_scope: Optional[set[str]],
) -> list[GallerySummary]:
    """Group new rows by gallery (in first-seen order) and compute the
    UI-friendly summary: work count, cat-no range, in-scope flag."""
    by_gallery: dict[str, dict] = {}
    order: list[str] = []
    for row in new:
        g = row.gallery or "Uncategorised"
        if g not in by_gallery:
            order.append(g)
            by_gallery[g] = {"count": 0, "cat_nos": []}
        by_gallery[g]["count"] += 1
        # Best-effort numeric cat_no for range display; non-numeric ignored
        try:
            n = int(str(row.cat_no).strip())
            by_gallery[g]["cat_nos"].append(n)
        except (TypeError, ValueError):
            pass

    summaries: list[GallerySummary] = []
    for pos, name in enumerate(order, start=1):
        info = by_gallery[name]
        cat_nos = info["cat_nos"]
        in_scope = gallery_scope is None or name in gallery_scope
        summaries.append(
            GallerySummary(
                name=name,
                position=pos,
                work_count=info["count"],
                cat_no_min=min(cat_nos) if cat_nos else None,
                cat_no_max=max(cat_nos) if cat_nos else None,
                in_scope=in_scope,
            )
        )
    return summaries
