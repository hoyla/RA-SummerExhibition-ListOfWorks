"""Renderer for the Artists' Index export.

Produces InDesign Tagged Text (primary format), with the same multi-format
support pattern as the List of Works renderer.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
from sqlalchemy.orm import Session
from uuid import UUID

from backend.app.models.index_artist_model import IndexArtist
from backend.app.models.index_cat_number_model import IndexCatNumber


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class IndexExportConfig:
    """Configuration for Artists' Index export rendering."""

    # Paragraph style for each entry
    entry_style: str = "Index Text"

    # Character styles
    ra_surname_style: str = "RA Member Cap Surname"
    ra_caps_style: str = "RA Caps"
    cat_no_style: str = "Index works numbers"
    honorifics_style: str = "Small caps"  # for non-RA honorifics
    expert_numbers_style: str = "Expert numbers"  # for numeric-heavy names

    # Behaviour
    quals_lowercase: bool = True  # lowercase the quals string
    expert_numbers_enabled: bool = False  # apply Expert numbers style to leading digits
    cat_no_separator: str = ","  # separator between catalogue numbers


DEFAULT_INDEX_CONFIG = IndexExportConfig()


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------


@dataclass
class ArtistExportEntry:
    """Fully resolved artist entry ready for rendering."""

    title: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    quals: Optional[str]
    company: Optional[str]
    is_ra_member: bool
    is_company: bool
    sort_key: str
    courtesy: Optional[str]  # the courtesy line for this group (or None)
    cat_nos: List[int]  # catalogue numbers for this courtesy group


def collect_index_entries(db: Session, import_id: UUID) -> List[ArtistExportEntry]:
    """Collect all index entries for an import, grouped by artist and courtesy.

    Returns a list of ArtistExportEntry sorted by sort_key, with one entry
    per artist per distinct courtesy value.
    """
    artists = (
        db.query(IndexArtist)
        .filter(
            IndexArtist.import_id == import_id, IndexArtist.include_in_export.is_(True)
        )
        .order_by(IndexArtist.sort_key, IndexArtist.row_number)
        .all()
    )

    entries: List[ArtistExportEntry] = []
    for artist in artists:
        cat_numbers = (
            db.query(IndexCatNumber)
            .filter(IndexCatNumber.artist_id == artist.id)
            .order_by(IndexCatNumber.cat_no)
            .all()
        )

        # Group cat numbers by courtesy value
        courtesy_groups: Dict[Optional[str], List[int]] = defaultdict(list)
        for cn in cat_numbers:
            courtesy_groups[cn.courtesy].append(cn.cat_no)

        # No-courtesy group first, then courtesy groups alphabetically
        group_keys = sorted(
            courtesy_groups.keys(),
            key=lambda k: (k is not None, k or ""),
        )

        for courtesy_key in group_keys:
            entries.append(
                ArtistExportEntry(
                    title=artist.title,
                    first_name=artist.first_name,
                    last_name=artist.last_name,
                    quals=artist.quals,
                    company=artist.company,
                    is_ra_member=artist.is_ra_member,
                    is_company=artist.is_company,
                    sort_key=artist.sort_key,
                    courtesy=courtesy_key,
                    cat_nos=courtesy_groups[courtesy_key],
                )
            )

    return entries


# ---------------------------------------------------------------------------
# InDesign Tagged Text renderer
# ---------------------------------------------------------------------------


def _cstyle(style: str, text: str) -> str:
    """Wrap text in an InDesign character style tag."""
    if not style:
        return text
    return f"<cstyle:{style}>{text}<cstyle:>"


def _has_leading_digit(name: Optional[str]) -> bool:
    """Check if name starts with a digit (e.g. '8014', '51 Architecture')."""
    if not name:
        return False
    return name[0].isdigit()


def _render_name_part(
    entry: ArtistExportEntry,
    cfg: IndexExportConfig,
) -> str:
    """Render the name portion of an index entry.

    Examples:
    - Simple: 'Adams, Roger, '
    - RA member: '<cstyle:RA Member Cap Surname>Parker, <cstyle:>Cornelia, '
    - Single name RA: '<cstyle:RA Member Cap Surname>Assemble, <cstyle:>'
    - Company: 'AKT II, '
    """
    parts: List[str] = []

    # Determine the "display surname" and "display rest"
    surname = entry.last_name or entry.first_name or entry.company or ""
    rest_parts: List[str] = []

    if entry.last_name and entry.first_name:
        # Normal case: "Last, [Title] First"
        if entry.title:
            rest_parts.append(entry.title)
        rest_parts.append(entry.first_name)
    elif entry.last_name and not entry.first_name:
        # Company or single-name entity — surname only
        pass
    elif not entry.last_name and entry.first_name:
        # Single name (e.g. "Assemble") — first_name used as surname
        pass

    # Expert numbers for leading-digit names
    if cfg.expert_numbers_enabled and _has_leading_digit(surname):
        # Extract the numeric prefix
        i = 0
        while i < len(surname) and surname[i].isdigit():
            i += 1
        numeric_part = surname[:i]
        text_part = surname[i:]
        surname_display = _cstyle(cfg.expert_numbers_style, numeric_part) + text_part
    else:
        surname_display = surname

    # Apply RA surname styling
    if entry.is_ra_member:
        parts.append(_cstyle(cfg.ra_surname_style, surname_display + ", "))
    else:
        parts.append(surname_display + ", ")

    # Add the rest (title + first name)
    if rest_parts:
        parts.append(" ".join(rest_parts) + ", ")

    return "".join(parts)


def _render_quals(quals: Optional[str], is_ra: bool, cfg: IndexExportConfig) -> str:
    """Render qualifications with appropriate styling."""
    if not quals:
        return ""
    display = quals.lower() if cfg.quals_lowercase else quals
    if is_ra:
        return _cstyle(cfg.ra_caps_style, display + ", ")
    else:
        return _cstyle(cfg.honorifics_style, display + ", ")


def _render_courtesy(courtesy: Optional[str], company: Optional[str]) -> str:
    """Render courtesy line or company name."""
    # Company name (for RA members with a practice)
    if company and not courtesy:
        # Only include if the artist isn't purely a company entry
        return company + ", "
    if courtesy:
        return courtesy + ", "
    return ""


def _render_cat_nos(cat_nos: List[int], cfg: IndexExportConfig) -> str:
    """Render catalogue numbers, each individually styled.

    Output: '<cstyle:X>101<cstyle:>,<cstyle:X> 205<cstyle:>'
    """
    if not cat_nos:
        return ""
    style = cfg.cat_no_style
    parts: List[str] = []
    for i, num in enumerate(cat_nos):
        if i == 0:
            parts.append(_cstyle(style, str(num)))
        else:
            # Comma outside the style, space inside the next styled span
            parts.append(f",{_cstyle(style, ' ' + str(num))}")
    return "".join(parts)


def render_index_tagged_text(
    entries: List[ArtistExportEntry],
    cfg: IndexExportConfig = DEFAULT_INDEX_CONFIG,
) -> str:
    """Render a list of ArtistExportEntry objects as InDesign Tagged Text."""
    lines: List[str] = ["<ASCII-MAC>"]

    for entry in entries:
        line_parts: List[str] = [f"<pstyle:{cfg.entry_style}>"]

        # Name
        line_parts.append(_render_name_part(entry, cfg))

        # Qualifications
        line_parts.append(_render_quals(entry.quals, entry.is_ra_member, cfg))

        # Courtesy / company
        # For company entries that are also RA members (like "Adjaye Associates"),
        # the company name goes after quals.
        # For non-company entries with a courtesy, it goes after quals.
        # For company entries without courtesy, company name is the "surname" already.
        if not entry.is_company:
            line_parts.append(_render_courtesy(entry.courtesy, entry.company))
        else:
            # Company entry — courtesy still applies if present
            if entry.courtesy:
                line_parts.append(entry.courtesy + ", ")

        # Cat numbers
        line_parts.append(_render_cat_nos(entry.cat_nos, cfg))

        lines.append("".join(line_parts))

    return "\r".join(lines)
