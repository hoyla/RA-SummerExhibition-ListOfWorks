"""
Index override resolution.

Provides ``resolve_index_artist`` which merges an IndexArtist's auto-detected
fields with any IndexArtistOverride row to produce effective values for
the export renderer and preview endpoints.
"""

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class EffectiveIndexArtist:
    """Resolved field values for a single index artist."""

    # Identity / display
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


def resolve_index_artist(artist, override) -> EffectiveIndexArtist:
    """Merge an IndexArtist with an optional IndexArtistOverride.

    Rules:
      - If ``override.is_company_override`` is not None, it takes precedence
        over the auto-detected ``artist.is_company``.
      - All other fields are taken from the artist directly (not yet
        overridable, but the structure is extensible).

    Parameters
    ----------
    artist:
        SQLAlchemy IndexArtist instance.
    override:
        SQLAlchemy IndexArtistOverride instance, or None.
    """
    auto_company = bool(artist.is_company)

    if override is not None and override.is_company_override is not None:
        effective_company = override.is_company_override
    else:
        effective_company = auto_company

    return EffectiveIndexArtist(
        title=artist.title,
        first_name=artist.first_name,
        last_name=artist.last_name,
        quals=artist.quals,
        company=artist.company,
        second_artist=getattr(artist, "second_artist", None),
        is_ra_member=bool(artist.is_ra_member),
        is_company=effective_company,
        is_company_auto=auto_company,
        sort_key=artist.sort_key or "",
        include_in_export=bool(artist.include_in_export),
    )
