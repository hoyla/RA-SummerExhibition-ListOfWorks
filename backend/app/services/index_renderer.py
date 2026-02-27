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
from backend.app.models.index_override_model import IndexArtistOverride
from backend.app.services.index_override_service import (
    resolve_index_artist,
    build_known_artist_cache,
    lookup_known_artist,
)
from backend.app.services.index_importer import is_ra_member


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
    cat_no_separator_style: str = ""  # character style for the separator (empty = none)

    # Section separator (between letter groups)
    section_separator: str = (
        "paragraph"  # paragraph | column_break | frame_break | page_break | none
    )
    section_separator_style: str = ""  # paragraph style for the separator line

    # Letter headings (e.g. "A", "B", "C" at the start of each group)
    letter_heading_enabled: bool = False
    letter_heading_style: str = (
        ""  # paragraph style for the heading (empty = entry_style)
    )


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
    artist2_first_name: Optional[str]
    artist2_last_name: Optional[str]
    artist2_quals: Optional[str]
    artist3_first_name: Optional[str]
    artist3_last_name: Optional[str]
    artist3_quals: Optional[str]
    artist1_ra_styled: bool
    artist2_ra_styled: bool
    artist3_ra_styled: bool
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

    # Batch-fetch overrides
    artist_ids = [a.id for a in artists]
    overrides = (
        db.query(IndexArtistOverride)
        .filter(IndexArtistOverride.artist_id.in_(artist_ids))
        .all()
        if artist_ids
        else []
    )
    override_map = {str(o.artist_id): o for o in overrides}

    # Build known artist cache
    known_cache = build_known_artist_cache(db)

    entries: List[ArtistExportEntry] = []
    for artist in artists:
        known = lookup_known_artist(
            known_cache,
            artist.raw_first_name,
            artist.raw_last_name,
            artist.raw_quals,
        )
        eff = resolve_index_artist(artist, override_map.get(str(artist.id)), known)
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
                    title=eff.title,
                    first_name=eff.first_name,
                    last_name=eff.last_name,
                    quals=eff.quals,
                    company=eff.company,
                    artist2_first_name=eff.artist2_first_name,
                    artist2_last_name=eff.artist2_last_name,
                    artist2_quals=eff.artist2_quals,
                    artist3_first_name=eff.artist3_first_name,
                    artist3_last_name=eff.artist3_last_name,
                    artist3_quals=eff.artist3_quals,
                    artist1_ra_styled=eff.artist1_ra_styled,
                    artist2_ra_styled=eff.artist2_ra_styled,
                    artist3_ra_styled=eff.artist3_ra_styled,
                    is_ra_member=eff.is_ra_member,
                    is_company=eff.is_company,
                    sort_key=eff.sort_key,
                    courtesy=courtesy_key,
                    cat_nos=courtesy_groups[courtesy_key],
                )
            )

    # Re-sort by resolved sort key (known artists may change ordering)
    entries.sort(key=lambda e: e.sort_key)
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
    has_quals: bool = False,
) -> str:
    """Render the name portion of an index entry.

    Character styles wrap only the value, never separators.

    Examples:
    - Simple: 'Adams, Roger, '
    - RA member: '<cstyle:RA Member Cap Surname>Parker<cstyle:>, Cornelia, '
    - Single name RA: '<cstyle:RA Member Cap Surname>Assemble<cstyle:>, '
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

    # When quals follow directly, the last separator is a space not a comma
    # so that we get "Parker, Cornelia cbe ra" not "Parker, Cornelia, cbe ra".
    surname_sep = " " if (has_quals and not rest_parts) else ", "
    rest_sep = " " if has_quals else ", "

    # Apply RA surname styling — style wraps only the name, not the separator
    if entry.artist1_ra_styled:
        parts.append(_cstyle(cfg.ra_surname_style, surname_display) + surname_sep)
    else:
        parts.append(surname_display + surname_sep)

    # Add the rest (title + first name)
    if rest_parts:
        parts.append(" ".join(rest_parts) + rest_sep)

    return "".join(parts)


def _render_quals(quals: Optional[str], is_ra: bool, cfg: IndexExportConfig) -> str:
    """Render qualifications with appropriate styling.

    Character style wraps only the quals text; the trailing ', ' separator
    is outside the style.
    """
    if not quals:
        return ""
    display = quals.lower() if cfg.quals_lowercase else quals
    if is_ra:
        return _cstyle(cfg.ra_caps_style, display) + ", "
    else:
        return _cstyle(cfg.honorifics_style, display) + ", "


def _render_courtesy(courtesy: Optional[str], company: Optional[str]) -> str:
    """Render courtesy line or company name."""
    # Company name (for RA members with a practice)
    if company and not courtesy:
        # Only include if the artist isn't purely a company entry
        return company + ", "
    if courtesy:
        return courtesy + ", "
    return ""


def _render_additional_artist(
    first_name: Optional[str],
    last_name: Optional[str],
    quals: Optional[str],
    ra_styled: bool,
    cfg: IndexExportConfig,
    *,
    include_and: bool = True,
) -> str:
    """Render an additional artist (artist2 or artist3) with styling.

    Character styles wrap only the value, not surrounding separators.
    When *include_and* is False the 'and ' prefix is omitted (used for
    the non-final artist in a 3-artist entry where commas suffice).

    Returns formatted string like:
      'and Peter St John, '
      'and <cstyle:RA Member Cap Surname>St John<cstyle:> Peter cbe ra, '
    """
    if not first_name and not last_name:
        return ""

    parts: List[str] = ["and "] if include_and else []
    if first_name:
        parts.append(first_name + " ")
    surname = last_name or ""
    if ra_styled and surname:
        parts.append(_cstyle(cfg.ra_surname_style, surname))
    else:
        parts.append(surname)

    if quals:
        display_q = quals.lower() if cfg.quals_lowercase else quals
        parts.append(" ")
        if ra_styled:
            parts.append(_cstyle(cfg.ra_caps_style, display_q) + ", ")
        else:
            parts.append(_cstyle(cfg.honorifics_style, display_q) + ", ")
    else:
        parts.append(", ")

    return "".join(parts)


def _section_sep(name: str, style: str = "") -> str:
    """Return the InDesign tagged-text string for a section separator."""
    prefix = f"<pstyle:{style}>" if style else ""
    if name == "none":
        return ""
    if name == "column_break":
        return f"{prefix}<cnxc:Column>\r"
    if name == "frame_break":
        return f"{prefix}<cnxc:Frame>\r"
    if name == "page_break":
        return f"{prefix}<cnxc:Page>\r"
    if name == "2paragraph":
        return f"{prefix}\r{prefix}\r"
    # Default: paragraph (1 blank line)
    return f"{prefix}\r"


def _render_cat_nos(cat_nos: List[int], cfg: IndexExportConfig) -> str:
    """Render catalogue numbers, each individually styled.

    Character style wraps only the number itself; separators (comma/space)
    remain outside the style.

    Output: '<cstyle:X>101<cstyle:>, <cstyle:X>205<cstyle:>'
    """
    if not cat_nos:
        return ""
    style = cfg.cat_no_style
    sep = cfg.cat_no_separator
    sep_style = cfg.cat_no_separator_style
    parts: List[str] = []
    for i, num in enumerate(cat_nos):
        if i == 0:
            parts.append(_cstyle(style, str(num)))
        else:
            styled_sep = _cstyle(sep_style, sep)
            parts.append(f"{styled_sep} {_cstyle(style, str(num))}")
    return "".join(parts)


def _letter_key(entry: ArtistExportEntry) -> str:
    """Return the uppercase first letter of the sort key, or '#' for digits."""
    ch = (entry.sort_key or "?")[0].upper()
    return "#" if ch.isdigit() else ch


def render_index_tagged_text(
    entries: List[ArtistExportEntry],
    cfg: IndexExportConfig = DEFAULT_INDEX_CONFIG,
) -> str:
    """Render a list of ArtistExportEntry objects as InDesign Tagged Text."""
    lines: List[str] = ["<ASCII-MAC>"]

    current_letter: Optional[str] = None
    for entry in entries:
        letter = _letter_key(entry)
        if letter != current_letter:
            if current_letter is not None:
                # Insert section separator between letter groups
                sep = _section_sep(cfg.section_separator, cfg.section_separator_style)
                if sep:
                    # Strip trailing \r because "\r".join() already adds one
                    lines.append(sep.rstrip("\r"))
            current_letter = letter
            # Optional letter heading (e.g. "A", "B", ...)
            if cfg.letter_heading_enabled:
                h_style = cfg.letter_heading_style or cfg.entry_style
                lines.append(f"<pstyle:{h_style}>{letter}")
        line_parts: List[str] = [f"<pstyle:{cfg.entry_style}>"]

        # Name (pass has_quals so separator is space not comma before quals)
        has_quals = bool(entry.quals)
        line_parts.append(_render_name_part(entry, cfg, has_quals=has_quals))

        # Qualifications
        line_parts.append(_render_quals(entry.quals, entry.is_ra_member, cfg))

        # Additional artists (structured, with per-artist RA styling)
        # When there are 3 artists, omit "and" before artist 2 so we get
        # "Surname, First, Second Artist, and Third Artist, ..." instead of
        # "Surname, First, and Second Artist, and Third Artist, ..."
        has_artist3 = bool(entry.artist3_first_name or entry.artist3_last_name)
        a2 = _render_additional_artist(
            entry.artist2_first_name,
            entry.artist2_last_name,
            entry.artist2_quals,
            entry.artist2_ra_styled,
            cfg,
            include_and=not has_artist3,
        )
        if a2:
            line_parts.append(a2)

        a3 = _render_additional_artist(
            entry.artist3_first_name,
            entry.artist3_last_name,
            entry.artist3_quals,
            entry.artist3_ra_styled,
            cfg,
        )
        if a3:
            line_parts.append(a3)

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
