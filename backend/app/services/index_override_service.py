"""
Index override resolution.

Provides ``resolve_index_artist`` which merges an IndexArtist's normalised
fields with an optional Known Artist lookup and an optional user override
to produce the effective values for the export renderer and preview.

Resolution priority (highest wins):
  1. User override (IndexArtistOverride)
  2. Known Artist lookup (KnownArtist)
  3. Normalised values (from importer heuristics)

The ``index_name`` field is a computed composite — the name as it will
appear in the printed index — built from the resolved values.  It is
never stored in the database.
"""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from sqlalchemy.orm import Session

from backend.app.models.known_artist_model import KnownArtist
from backend.app.services.index_importer import build_sort_key


# ---------------------------------------------------------------------------
# Known artist cache
# ---------------------------------------------------------------------------


def build_known_artist_cache(db: Session) -> Dict[Tuple[str, str], KnownArtist]:
    """Load known_artists table into a dict keyed by (match_first, match_last).

    Keys use lowered/stripped values; None fields normalise to empty string
    so that lookups are straightforward.
    """
    cache: Dict[Tuple[str, str], KnownArtist] = {}
    for ka in db.query(KnownArtist).all():
        key = (
            (ka.match_first_name or "").strip().lower(),
            (ka.match_last_name or "").strip().lower(),
        )
        cache[key] = ka
    return cache


def lookup_known_artist(
    cache: Dict[Tuple[str, str], KnownArtist],
    raw_first_name: Optional[str],
    raw_last_name: Optional[str],
) -> Optional[KnownArtist]:
    """Look up raw name values against the known_artists cache."""
    key = (
        (raw_first_name or "").strip().lower(),
        (raw_last_name or "").strip().lower(),
    )
    return cache.get(key)


# ---------------------------------------------------------------------------
# Index name
# ---------------------------------------------------------------------------


def build_index_name(
    last_name: Optional[str],
    first_name: Optional[str],
    title: Optional[str],
    quals: Optional[str],
    second_artist: Optional[str],
    is_company: bool,
) -> str:
    """Build the composite index name as it would appear in the printed index.

    Examples:
      Adams, Roger
      Parker, Cornelia, cbe ra
      Adjaye, Sir David, om obe ra
      Boyd & Evans
      Assemble, ra
      Caruso, Adam, ra, and Peter St John
    """
    surname = last_name or first_name or ""
    if not surname:
        return ""

    parts = [surname]

    # First name with optional title (only when we have both names and not a company)
    if not is_company and last_name and first_name:
        rest = []
        if title:
            rest.append(title)
        rest.append(first_name)
        parts.append(" ".join(rest))

    # Quals (lowercased per print convention)
    if quals:
        parts.append(quals.lower())

    # Second artist suffix
    if second_artist:
        parts.append(second_artist)

    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Effective artist dataclass
# ---------------------------------------------------------------------------


@dataclass
class EffectiveIndexArtist:
    """Resolved field values for a single index artist."""

    # Computed display name
    index_name: str

    # Identity / display (resolved)
    title: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    quals: Optional[str]
    company: Optional[str]
    second_artist: Optional[str]

    # Flags — effective (after override)
    is_ra_member: bool
    is_company: bool

    # Auto-detected baseline (for UI diff display)
    is_company_auto: bool

    sort_key: str
    include_in_export: bool


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def resolve_index_artist(artist, override, known_artist=None) -> EffectiveIndexArtist:
    """Merge an IndexArtist with an optional KnownArtist and IndexArtistOverride.

    Resolution priority (highest wins):
      1. ``override.is_company_override`` — user override for company flag
      2. ``known_artist.resolved_*`` — known artist lookup results
      3. ``artist.*`` — normalised values from importer

    The ``""`` (empty-string) convention for known artist fields means
    "clear this field" (set to None).  ``None`` means "don't override".

    Parameters
    ----------
    artist:
        SQLAlchemy IndexArtist instance.
    override:
        SQLAlchemy IndexArtistOverride instance, or None.
    known_artist:
        SQLAlchemy KnownArtist instance, or None.
    """
    # Start with normalised values from the importer
    first_name = artist.first_name
    last_name = artist.last_name
    quals = artist.quals
    second_artist = getattr(artist, "second_artist", None)
    company = artist.company
    auto_company = bool(artist.is_company)

    # Layer 2: Known artist overrides
    if known_artist is not None:
        if known_artist.resolved_first_name is not None:
            first_name = known_artist.resolved_first_name or None
        if known_artist.resolved_last_name is not None:
            last_name = known_artist.resolved_last_name or None
        if known_artist.resolved_quals is not None:
            quals = known_artist.resolved_quals or None
        if known_artist.resolved_second_artist is not None:
            second_artist = known_artist.resolved_second_artist or None

    # Company flag: override > known_artist > auto-detected
    if override is not None and override.is_company_override is not None:
        effective_company = override.is_company_override
    elif known_artist is not None and known_artist.resolved_is_company is not None:
        effective_company = known_artist.resolved_is_company
    else:
        effective_company = auto_company

    # If resolved as company and no company name, use last_name
    if effective_company and not company:
        company = last_name

    # Recompute sort key from resolved values
    resolved_sort_key = build_sort_key(last_name, first_name)

    # Build composite index name
    index_name = build_index_name(
        last_name=last_name,
        first_name=first_name,
        title=artist.title,
        quals=quals,
        second_artist=second_artist,
        is_company=effective_company,
    )

    return EffectiveIndexArtist(
        index_name=index_name,
        title=artist.title,
        first_name=first_name,
        last_name=last_name,
        quals=quals,
        company=company,
        second_artist=second_artist,
        is_ra_member=bool(artist.is_ra_member),
        is_company=effective_company,
        is_company_auto=auto_company,
        sort_key=resolved_sort_key,
        include_in_export=bool(artist.include_in_export),
    )
