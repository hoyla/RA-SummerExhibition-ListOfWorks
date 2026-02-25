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


def build_known_artist_cache(db: Session) -> Dict[Tuple[str, str, str], KnownArtist]:
    """Load known_artists table into a dict keyed by (match_first, match_last, match_quals).

    Keys use lowered/stripped values; None fields normalise to empty string
    so that lookups are straightforward.  Entries with match_quals=NULL use
    "" as the quals key, allowing a two-pass lookup: first (first, last, quals)
    for an exact match, then (first, last, "") as a wildcard fallback.

    When a user-created entry (is_seeded=False) and a built-in entry
    (is_seeded=True) share the same match key, the user entry wins.
    """
    cache: Dict[Tuple[str, str, str], KnownArtist] = {}
    for ka in db.query(KnownArtist).all():
        key = (
            (ka.match_first_name or "").strip().lower(),
            (ka.match_last_name or "").strip().lower(),
            (ka.match_quals or "").strip().lower(),
        )
        # User entries (is_seeded=False) take priority over seeded ones
        if key not in cache or not ka.is_seeded:
            cache[key] = ka
    return cache


def lookup_known_artist(
    cache: Dict[Tuple[str, str, str], KnownArtist],
    raw_first_name: Optional[str],
    raw_last_name: Optional[str],
    raw_quals: Optional[str] = None,
) -> Optional[KnownArtist]:
    """Look up raw name values against the known_artists cache.

    First tries an exact match including quals.  If no match is found,
    falls back to entries where match_quals is NULL (wildcard).
    """
    first = (raw_first_name or "").strip().lower()
    last = (raw_last_name or "").strip().lower()
    quals = (raw_quals or "").strip().lower()
    # Try exact match with quals first
    if quals:
        result = cache.get((first, last, quals))
        if result is not None:
            return result
    # Fallback: entries where match_quals is NULL (wildcard)
    return cache.get((first, last, ""))


# ---------------------------------------------------------------------------
# Index name
# ---------------------------------------------------------------------------


def build_index_name(
    last_name: Optional[str],
    first_name: Optional[str],
    title: Optional[str],
    quals: Optional[str],
    artist2_first_name: Optional[str],
    artist2_last_name: Optional[str],
    artist2_quals: Optional[str],
    artist3_first_name: Optional[str],
    artist3_last_name: Optional[str],
    artist3_quals: Optional[str],
    is_company: bool,
) -> str:
    """Build the composite index name as it would appear in the printed index.

    Quals follow the name with a space (no comma), matching the LoW
    convention for honorifics.  Additional artists are appended with
    ", and ..." connectors.

    Examples:
      Adams, Roger
      Parker, Cornelia cbe ra
      Adjaye, Sir David om obe ra
      Boyd & Evans
      Assemble ra
      Caruso, Adam ra, and Peter St John
      Caruso, Adam ra, and Peter St John cbe
    """
    surname = last_name or first_name or ""
    if not surname:
        return ""

    # Build the name portion (comma-separated surname + first name)
    name_parts = [surname]
    if not is_company and last_name and first_name:
        rest = []
        if title:
            rest.append(title)
        rest.append(first_name)
        name_parts.append(" ".join(rest))

    name = ", ".join(name_parts)

    # Quals follow with a space (no comma)
    if quals:
        name += " " + quals.lower()

    # Second artist suffix (never for companies)
    if not is_company:
        a2_name = _format_additional_artist(
            artist2_first_name, artist2_last_name, artist2_quals
        )
        if a2_name:
            name += ", and " + a2_name

        a3_name = _format_additional_artist(
            artist3_first_name, artist3_last_name, artist3_quals
        )
        if a3_name:
            name += ", and " + a3_name

    return name


def _format_additional_artist(
    first_name: Optional[str],
    last_name: Optional[str],
    quals: Optional[str],
) -> Optional[str]:
    """Format an additional artist name for the index name composite."""
    parts = []
    if first_name:
        parts.append(first_name)
    if last_name:
        parts.append(last_name)
    if not parts:
        return None
    result = " ".join(parts)
    if quals:
        result += " " + quals.lower()
    return result


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

    # Multi-artist fields (resolved)
    artist2_first_name: Optional[str]
    artist2_last_name: Optional[str]
    artist2_quals: Optional[str]
    artist3_first_name: Optional[str]
    artist3_last_name: Optional[str]
    artist3_quals: Optional[str]

    # Per-artist RA styling flags (resolved)
    artist1_ra_styled: bool
    artist2_ra_styled: bool
    artist3_ra_styled: bool

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
      1. ``override.*_override`` — user overrides for each field
      2. ``known_artist.resolved_*`` — known artist lookup results
      3. ``artist.*`` — normalised values from importer

    The ``""`` (empty-string) convention for known artist and override
    fields means "clear this field" (set to None).  ``None`` means
    "don't override".

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
    title = artist.title
    quals = artist.quals
    artist2_first_name = getattr(artist, "artist2_first_name", None)
    artist2_last_name = getattr(artist, "artist2_last_name", None)
    artist2_quals = getattr(artist, "artist2_quals", None)
    artist3_first_name = getattr(artist, "artist3_first_name", None)
    artist3_last_name = getattr(artist, "artist3_last_name", None)
    artist3_quals = getattr(artist, "artist3_quals", None)
    artist1_ra_styled = bool(getattr(artist, "artist1_ra_styled", False))
    artist2_ra_styled = bool(getattr(artist, "artist2_ra_styled", False))
    artist3_ra_styled = bool(getattr(artist, "artist3_ra_styled", False))
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
        if getattr(known_artist, "resolved_artist2_first_name", None) is not None:
            artist2_first_name = known_artist.resolved_artist2_first_name or None
        if getattr(known_artist, "resolved_artist2_last_name", None) is not None:
            artist2_last_name = known_artist.resolved_artist2_last_name or None
        if getattr(known_artist, "resolved_artist2_quals", None) is not None:
            artist2_quals = known_artist.resolved_artist2_quals or None
        if getattr(known_artist, "resolved_artist3_first_name", None) is not None:
            artist3_first_name = known_artist.resolved_artist3_first_name or None
        if getattr(known_artist, "resolved_artist3_last_name", None) is not None:
            artist3_last_name = known_artist.resolved_artist3_last_name or None
        if getattr(known_artist, "resolved_artist3_quals", None) is not None:
            artist3_quals = known_artist.resolved_artist3_quals or None
        if getattr(known_artist, "resolved_artist1_ra_styled", None) is not None:
            artist1_ra_styled = bool(known_artist.resolved_artist1_ra_styled)
        if getattr(known_artist, "resolved_artist2_ra_styled", None) is not None:
            artist2_ra_styled = bool(known_artist.resolved_artist2_ra_styled)
        if getattr(known_artist, "resolved_artist3_ra_styled", None) is not None:
            artist3_ra_styled = bool(known_artist.resolved_artist3_ra_styled)

    # Layer 3 (highest priority): User overrides
    if override is not None:
        if override.first_name_override is not None:
            first_name = override.first_name_override or None
        if override.last_name_override is not None:
            last_name = override.last_name_override or None
        if override.title_override is not None:
            title = override.title_override or None
        if override.quals_override is not None:
            quals = override.quals_override or None
        if getattr(override, "artist2_first_name_override", None) is not None:
            artist2_first_name = override.artist2_first_name_override or None
        if getattr(override, "artist2_last_name_override", None) is not None:
            artist2_last_name = override.artist2_last_name_override or None
        if getattr(override, "artist2_quals_override", None) is not None:
            artist2_quals = override.artist2_quals_override or None
        if getattr(override, "artist3_first_name_override", None) is not None:
            artist3_first_name = override.artist3_first_name_override or None
        if getattr(override, "artist3_last_name_override", None) is not None:
            artist3_last_name = override.artist3_last_name_override or None
        if getattr(override, "artist3_quals_override", None) is not None:
            artist3_quals = override.artist3_quals_override or None
        if getattr(override, "artist1_ra_styled_override", None) is not None:
            artist1_ra_styled = bool(override.artist1_ra_styled_override)
        if getattr(override, "artist2_ra_styled_override", None) is not None:
            artist2_ra_styled = bool(override.artist2_ra_styled_override)
        if getattr(override, "artist3_ra_styled_override", None) is not None:
            artist3_ra_styled = bool(override.artist3_ra_styled_override)
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

    # Companies never have additional artists — the full name is
    # already in last_name (e.g. "Boyd & Evans").  Clear any artefacts
    # left over from multi-artist parsing.
    if effective_company:
        artist2_first_name = None
        artist2_last_name = None
        artist2_quals = None
        artist3_first_name = None
        artist3_last_name = None
        artist3_quals = None

    # Recompute sort key from resolved values
    resolved_sort_key = build_sort_key(last_name, first_name)

    # Build composite index name
    index_name = build_index_name(
        last_name=last_name,
        first_name=first_name,
        title=title,
        quals=quals,
        artist2_first_name=artist2_first_name,
        artist2_last_name=artist2_last_name,
        artist2_quals=artist2_quals,
        artist3_first_name=artist3_first_name,
        artist3_last_name=artist3_last_name,
        artist3_quals=artist3_quals,
        is_company=effective_company,
    )

    return EffectiveIndexArtist(
        index_name=index_name,
        title=title,
        first_name=first_name,
        last_name=last_name,
        quals=quals,
        company=company,
        artist2_first_name=artist2_first_name,
        artist2_last_name=artist2_last_name,
        artist2_quals=artist2_quals,
        artist3_first_name=artist3_first_name,
        artist3_last_name=artist3_last_name,
        artist3_quals=artist3_quals,
        artist1_ra_styled=artist1_ra_styled,
        artist2_ra_styled=artist2_ra_styled,
        artist3_ra_styled=artist3_ra_styled,
        is_ra_member=bool(artist.is_ra_member),
        is_company=effective_company,
        is_company_auto=auto_company,
        sort_key=resolved_sort_key,
        include_in_export=bool(artist.include_in_export),
    )
