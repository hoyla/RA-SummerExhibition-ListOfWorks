"""
Cross-dataset comparison service.

Compares a List of Works import against an Artists' Index import by
catalogue number, producing a structured report of:
  - catalogue numbers present in one dataset but not the other
  - name matches / mismatches for shared catalogue numbers

The comparison uses *resolved* values (after overrides), so editorial
corrections are reflected.  It is a pure read-only computation — no
database writes.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from backend.app.models.import_model import Import
from backend.app.models.index_artist_model import IndexArtist
from backend.app.models.index_cat_number_model import IndexCatNumber
from backend.app.models.index_override_model import IndexArtistOverride
from backend.app.models.work_model import Work
from backend.app.models.override_model import WorkOverride
from backend.app.services.override_service import resolve_effective_work
from backend.app.services.index_override_service import (
    build_known_artist_cache,
    lookup_known_artist,
    resolve_index_artist,
)


# ---------------------------------------------------------------------------
# Match classification
# ---------------------------------------------------------------------------


class MatchLevel(str, Enum):
    """How closely the artist name matches between LoW and Index."""

    exact = "exact"
    """Resolved names are identical (case-insensitive)."""

    equivalent = "equivalent"
    """Same name components, different formatting (e.g. word order, comma)."""

    partial = "partial"
    """Core name matches but qualifications/titles differ."""

    none = "none"
    """Names do not match."""


# ---------------------------------------------------------------------------
# Per-entry result
# ---------------------------------------------------------------------------


@dataclass
class ComparisonEntry:
    """Comparison result for a single catalogue number."""

    cat_no: int

    # LoW side (None if cat number missing from LoW)
    low_artist_name: Optional[str] = None
    low_artist_honorifics: Optional[str] = None
    low_work_id: Optional[str] = None

    # Index side (None if cat number missing from Index)
    index_name: Optional[str] = None
    index_first_name: Optional[str] = None
    index_last_name: Optional[str] = None
    index_title: Optional[str] = None
    index_quals: Optional[str] = None
    index_is_company: Optional[bool] = None
    index_artist_id: Optional[str] = None
    index_courtesy: Optional[str] = None

    match_level: MatchLevel = MatchLevel.none
    differences: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


@dataclass
class ComparisonSummary:
    total_low: int = 0
    total_index: int = 0
    in_both: int = 0
    only_in_low: int = 0
    only_in_index: int = 0
    match_exact: int = 0
    match_equivalent: int = 0
    match_partial: int = 0
    match_none: int = 0


# ---------------------------------------------------------------------------
# Full result
# ---------------------------------------------------------------------------


@dataclass
class ComparisonResult:
    low_import_id: str
    index_import_id: str
    summary: ComparisonSummary
    entries: List[ComparisonEntry]


# ---------------------------------------------------------------------------
# Name parsing helpers
# ---------------------------------------------------------------------------


def _normalise_words(text: Optional[str]) -> Set[str]:
    """Lower-case, strip punctuation (commas, periods), split into word set."""
    if not text:
        return set()
    cleaned = text.lower().replace(",", " ").replace(".", " ")
    return {w for w in cleaned.split() if w}


def _extract_low_name_parts(
    artist_name: Optional[str],
    artist_honorifics: Optional[str],
) -> Tuple[str, str, Set[str]]:
    """Parse a LoW artist string into (first_name_guess, last_name_guess, quals_words).

    LoW stores artist as a single combined string like "Ryan Gander" with
    honorifics separately as "RA".  We attempt to split first/last for
    comparison against the Index's structured fields.

    For multi-word names we assume the last word is the surname — this is
    imperfect but covers the vast majority of cases.  The comparison engine
    uses this as one signal among several.
    """
    name = (artist_name or "").strip()
    quals = (artist_honorifics or "").strip()

    if not name:
        return ("", "", _normalise_words(quals))

    parts = name.split()
    if len(parts) == 1:
        return ("", parts[0], _normalise_words(quals))

    # Last word is assumed surname; everything before is first name(s)
    return (" ".join(parts[:-1]), parts[-1], _normalise_words(quals))


def _extract_index_name_parts(
    first_name: Optional[str],
    last_name: Optional[str],
    title: Optional[str],
    quals: Optional[str],
    is_company: bool,
) -> Tuple[str, str, Set[str]]:
    """Extract first, last, quals from resolved Index fields."""
    fn = (first_name or "").strip()
    ln = (last_name or "").strip()
    q = (quals or "").strip()
    t = (title or "").strip()

    # For companies, the "last_name" is the company name
    if is_company:
        return ("", ln, _normalise_words(q))

    # Combine title into first name for comparison purposes
    # (e.g. "Prof. Farshid" in Index vs "Farshid" in LoW)
    return (fn, ln, _normalise_words(q))


# ---------------------------------------------------------------------------
# Comparison logic
# ---------------------------------------------------------------------------


def _compare_names(
    low_artist_name: Optional[str],
    low_artist_honorifics: Optional[str],
    idx_first: Optional[str],
    idx_last: Optional[str],
    idx_title: Optional[str],
    idx_quals: Optional[str],
    idx_is_company: bool,
) -> Tuple[MatchLevel, List[str]]:
    """Compare a LoW artist name against Index structured name fields.

    Returns (match_level, list_of_difference_descriptions).
    """
    differences: List[str] = []

    low_first, low_last, low_quals = _extract_low_name_parts(
        low_artist_name, low_artist_honorifics
    )
    idx_first_clean, idx_last_clean, idx_quals_set = _extract_index_name_parts(
        idx_first, idx_last, idx_title, idx_quals, idx_is_company
    )

    # Build full name strings for exact comparison
    low_full = f"{low_first} {low_last}".strip().lower()
    idx_full = f"{idx_first_clean} {idx_last_clean}".strip().lower()

    # Build full-with-quals strings
    low_full_q = f"{low_full} {' '.join(sorted(low_quals))}".strip()
    idx_full_q = f"{idx_full} {' '.join(sorted(idx_quals_set))}".strip()

    # Check for exact match (name + quals)
    if low_full_q == idx_full_q:
        return (MatchLevel.exact, [])

    # Check last name match
    last_match = (
        low_last.lower() == idx_last_clean.lower()
        if (low_last and idx_last_clean)
        else False
    )

    # Check first name match (ignoring title prefixes in Index)
    low_first_lower = low_first.lower()
    idx_first_lower = idx_first_clean.lower()
    idx_title_lower = (idx_title or "").strip().lower()

    first_match = False
    if low_first_lower and idx_first_lower:
        if low_first_lower == idx_first_lower:
            first_match = True
        elif idx_title_lower:
            # LoW might include the title prefix: "Dame Tracey" vs Index first="Tracey", title="Dame"
            low_with_title = f"{idx_title_lower} {idx_first_lower}"
            if low_first_lower == low_with_title:
                first_match = True
            # Or LoW might have the title as a separate word: "The late Norman" vs "The late Prof. Norman"
            low_first_words = set(low_first_lower.split())
            idx_first_words = set(idx_first_lower.split())
            if idx_title_lower:
                idx_first_words.add(idx_title_lower.rstrip("."))
            # Check if all LoW words appear in Index (LoW may lack the title)
            if low_first_words and low_first_words <= idx_first_words:
                first_match = True
    elif not low_first_lower and not idx_first_lower:
        first_match = True  # both empty (e.g. companies)

    # Detect specific differences
    if not last_match:
        differences.append("last_name_different")
    if not first_match:
        # Check if it's a title prefix issue
        if idx_title_lower and last_match:
            differences.append("title_in_index_not_in_low")
        else:
            differences.append("first_name_different")

    # Quals comparison
    if low_quals != idx_quals_set:
        extra_in_index = idx_quals_set - low_quals
        extra_in_low = low_quals - idx_quals_set
        if extra_in_index:
            differences.append(
                f"extra_quals_in_index:{','.join(sorted(extra_in_index))}"
            )
        if extra_in_low:
            differences.append(f"extra_quals_in_low:{','.join(sorted(extra_in_low))}")

    # Classify match level
    if last_match and first_match:
        if not low_quals and not idx_quals_set:
            return (MatchLevel.exact, differences)
        if low_quals == idx_quals_set:
            return (MatchLevel.equivalent, differences)
        # Same person, different quals
        return (MatchLevel.partial, differences)
    elif last_match:
        # Last name matches but first name issues (often title prefix)
        return (MatchLevel.partial, differences)
    else:
        # Check word-set overlap as a fallback (handles companies, unusual name orders)
        low_all_words = _normalise_words(low_artist_name) | low_quals
        idx_all_words = (
            _normalise_words(f"{idx_first_clean} {idx_last_clean}") | idx_quals_set
        )
        if low_all_words and low_all_words == idx_all_words:
            return (MatchLevel.equivalent, differences)
        if low_all_words and idx_all_words and low_all_words & idx_all_words:
            return (MatchLevel.partial, differences)
        return (MatchLevel.none, differences)


# ---------------------------------------------------------------------------
# Main comparison function
# ---------------------------------------------------------------------------


def compare_datasets(
    db: Session,
    low_import_id: UUID,
    index_import_id: UUID,
) -> ComparisonResult:
    """Compare a LoW import against an Index import by catalogue number.

    Uses resolved values (after overrides/known-artist lookups) for both
    datasets.  The comparison is purely read-only.

    Parameters
    ----------
    db:
        Active SQLAlchemy session.
    low_import_id:
        UUID of a ``list_of_works`` Import.
    index_import_id:
        UUID of an ``artists_index`` Import.

    Returns
    -------
    ComparisonResult
        Structured comparison report with summary statistics and
        per-catalogue-number entries.
    """

    # ------------------------------------------------------------------
    # 1. Load LoW works with overrides
    # ------------------------------------------------------------------
    works = db.query(Work).filter(Work.import_id == low_import_id).all()
    work_ids = [w.id for w in works]
    overrides = (
        db.query(WorkOverride).filter(WorkOverride.work_id.in_(work_ids)).all()
        if work_ids
        else []
    )
    override_map: Dict[str, WorkOverride] = {str(o.work_id): o for o in overrides}

    # Build LoW map: cat_no (int) -> resolved values
    low_map: Dict[int, Tuple[str, str, str, str]] = (
        {}
    )  # cat_no -> (artist_name, honorifics, work_id, raw_cat_no)
    for w in works:
        eff = resolve_effective_work(w, override_map.get(str(w.id)))
        raw = eff.raw_cat_no or ""
        try:
            cat_no = int(raw)
        except (ValueError, TypeError):
            continue  # Skip non-numeric catalogue numbers
        low_map[cat_no] = (
            eff.artist_name or "",
            eff.artist_honorifics or "",
            str(w.id),
            raw,
        )

    # ------------------------------------------------------------------
    # 2. Load Index artists with overrides and known artists
    # ------------------------------------------------------------------
    artists = (
        db.query(IndexArtist).filter(IndexArtist.import_id == index_import_id).all()
    )
    artist_ids = [a.id for a in artists]

    # Batch-fetch cat numbers
    cat_numbers = (
        db.query(IndexCatNumber)
        .filter(IndexCatNumber.artist_id.in_(artist_ids))
        .order_by(IndexCatNumber.cat_no)
        .all()
        if artist_ids
        else []
    )

    # Batch-fetch overrides
    idx_overrides = (
        db.query(IndexArtistOverride)
        .filter(IndexArtistOverride.artist_id.in_(artist_ids))
        .all()
        if artist_ids
        else []
    )
    idx_override_map: Dict[str, IndexArtistOverride] = {
        str(o.artist_id): o for o in idx_overrides
    }

    # Build known artist cache
    known_cache = build_known_artist_cache(db)

    # Resolve each artist and map by cat number
    # Index map: cat_no -> (resolved fields, artist_id, courtesy)
    @dataclass
    class _IdxEntry:
        index_name: str
        first_name: str
        last_name: str
        title: Optional[str]
        quals: Optional[str]
        is_company: bool
        artist_id: str
        courtesy: Optional[str]

    idx_map: Dict[int, _IdxEntry] = {}

    # Pre-resolve each artist
    artist_resolved: Dict[str, object] = {}
    for a in artists:
        known = lookup_known_artist(
            known_cache, a.raw_first_name, a.raw_last_name, a.raw_quals
        )
        ovr = idx_override_map.get(str(a.id))
        eff = resolve_index_artist(a, ovr, known)
        artist_resolved[str(a.id)] = eff

    # Map cat numbers to resolved artist data
    for cn in cat_numbers:
        eff = artist_resolved.get(str(cn.artist_id))
        if eff is None:
            continue
        idx_map[cn.cat_no] = _IdxEntry(
            index_name=eff.index_name,
            first_name=eff.first_name or "",
            last_name=eff.last_name or "",
            title=eff.title,
            quals=eff.quals,
            is_company=eff.is_company,
            artist_id=str(cn.artist_id),
            courtesy=cn.courtesy,
        )

    # ------------------------------------------------------------------
    # 3. Compare
    # ------------------------------------------------------------------
    low_set = set(low_map.keys())
    idx_set = set(idx_map.keys())
    all_cat_nos = sorted(low_set | idx_set)

    summary = ComparisonSummary(
        total_low=len(low_set),
        total_index=len(idx_set),
        in_both=len(low_set & idx_set),
        only_in_low=len(low_set - idx_set),
        only_in_index=len(idx_set - low_set),
    )

    entries: List[ComparisonEntry] = []
    for cn in all_cat_nos:
        low_data = low_map.get(cn)
        idx_data = idx_map.get(cn)

        entry = ComparisonEntry(cat_no=cn)

        if low_data:
            entry.low_artist_name = low_data[0]
            entry.low_artist_honorifics = low_data[1]
            entry.low_work_id = low_data[2]

        if idx_data:
            entry.index_name = idx_data.index_name
            entry.index_first_name = idx_data.first_name
            entry.index_last_name = idx_data.last_name
            entry.index_title = idx_data.title
            entry.index_quals = idx_data.quals
            entry.index_is_company = idx_data.is_company
            entry.index_artist_id = idx_data.artist_id
            entry.index_courtesy = idx_data.courtesy

        # Determine match level
        if low_data and idx_data:
            level, diffs = _compare_names(
                entry.low_artist_name,
                entry.low_artist_honorifics,
                idx_data.first_name,
                idx_data.last_name,
                idx_data.title,
                idx_data.quals,
                idx_data.is_company,
            )
            entry.match_level = level
            entry.differences = diffs
        elif low_data and not idx_data:
            entry.match_level = MatchLevel.none
            entry.differences = ["missing_in_index"]
        elif idx_data and not low_data:
            entry.match_level = MatchLevel.none
            entry.differences = ["missing_in_low"]

        entries.append(entry)

        # Update summary counters
        if entry.match_level == MatchLevel.exact:
            summary.match_exact += 1
        elif entry.match_level == MatchLevel.equivalent:
            summary.match_equivalent += 1
        elif entry.match_level == MatchLevel.partial:
            summary.match_partial += 1
        else:
            summary.match_none += 1

    return ComparisonResult(
        low_import_id=str(low_import_id),
        index_import_id=str(index_import_id),
        summary=summary,
        entries=entries,
    )
