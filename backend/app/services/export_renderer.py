from dataclasses import dataclass, field
from typing import List, Optional
import csv
import io
import json
import xml.etree.ElementTree as ET
from sqlalchemy.orm import Session

from backend.app.models.section_model import Section
from backend.app.models.work_model import Work
from backend.app.models.override_model import WorkOverride
from backend.app.services.override_service import resolve_effective_work


# ---------------------------------------------------------------------------
# Component / separator model
# ---------------------------------------------------------------------------

COMPONENT_LABELS = {
    "work_number": "Work Number",
    "artist": "Artist",
    "title": "Title",
    "edition": "Edition info",
    "price": "Price",
    "medium": "Medium",
}


@dataclass
class ComponentConfig:
    """One component in the entry layout: which field and what separator follows it."""

    field: str
    separator_after: str = "tab"  # key in SEPARATOR_MAP
    omit_sep_when_empty: bool = (
        True  # suppress the separator when this component has no value
    )
    enabled: bool = True  # when False the component is excluded from export entirely
    max_line_chars: Optional[int] = (
        None  # wrap at this many chars per line (None = no wrap)
    )
    next_component_position: str = "end_of_text"  # "end_of_text" | "end_of_first_line"


DEFAULT_COMPONENTS: List[ComponentConfig] = [
    ComponentConfig("work_number", "tab"),
    ComponentConfig("artist", "tab"),
    ComponentConfig("title", "tab"),
    ComponentConfig("edition", "tab"),
    ComponentConfig("artwork", "tab", enabled=False),
    ComponentConfig("price", "none"),
    ComponentConfig("medium", "none"),
]


@dataclass
class ExportConfig:
    currency_symbol: str = "£"
    section_style: str = "SectionTitle"
    entry_style: str = "CatalogueEntry"
    edition_prefix: str = "edition of"
    edition_brackets: bool = True
    # Character styles — leave empty to suppress the tag
    cat_no_style: str = "CatNo"
    artist_style: str = "ArtistName"
    honorifics_style: str = "Honorifics"
    honorifics_lowercase: bool = False
    title_style: str = "WorkTitle"
    price_style: str = "Price"
    medium_style: str = "Medium"
    artwork_style: str = "Artwork"
    # Number formatting
    thousands_separator: str = ","
    decimal_places: int = 0
    # Entry layout
    leading_separator: str = "none"
    trailing_separator: str = "none"
    components: List[ComponentConfig] = field(
        default_factory=lambda: [
            ComponentConfig(
                c.field,
                c.separator_after,
                c.omit_sep_when_empty,
                c.enabled,
                c.max_line_chars,
                c.next_component_position,
            )
            for c in DEFAULT_COMPONENTS
        ]
    )


DEFAULT_CONFIG = ExportConfig()

from backend.app.models.ruleset_model import Ruleset
from uuid import UUID


def resolve_export_config(
    db: Session, ruleset_id: UUID | None = None
) -> Ruleset | None:
    """
    Resolve an export Ruleset from the database.

    - If ruleset_id provided: return that Ruleset (or None if not found)
    - Else: return the most recent non-archived Ruleset
    - If none exist: return None
    """

    if ruleset_id:
        return db.query(Ruleset).filter(Ruleset.id == ruleset_id).first()

    return (
        db.query(Ruleset)
        .filter(Ruleset.archived == False)
        .order_by(Ruleset.created_at.desc())
        .first()
    )


# ---------------------------------------------------------------------------
# Shared data collection
# ---------------------------------------------------------------------------


def _collect_export_data(import_id, db: Session, section_id=None) -> list[dict]:
    """
    Query sections and works for an import, apply override resolution, and
    return a normalised list of section dicts ready for any export format.

    Only works with include_in_export=True are included.

    Structure returned:
    [
        {
            "section_name": str,
            "position": int,
            "works": [
                {
                    "number": str | None,
                    "artist": str,
                    "honorifics": str | None,
                    "title": str,
                    "price_numeric": int | None,
                    "price_text": str,
                    "edition_total": int | None,
                    "edition_price_numeric": int | None,
                    "medium": str | None,
                },
                ...
            ],
        },
        ...
    ]
    """
    sections = (
        db.query(Section)
        .filter(Section.import_id == import_id)
        .order_by(Section.position.asc())
        .all()
    )
    if section_id is not None:
        sections = [s for s in sections if str(s.id) == str(section_id)]

    result = []

    for section in sections:
        works = (
            db.query(Work)
            .filter(Work.section_id == section.id)
            .filter(Work.include_in_export == True)
            .order_by(Work.position_in_section.asc())
            .all()
        )

        work_rows = []
        for w in works:
            override = db.query(WorkOverride).filter(WorkOverride.work_id == w.id).all()
            override = override[0] if override else None
            ew = resolve_effective_work(w, override)

            price_numeric = int(ew.price_numeric) if ew.price_numeric else None
            edition_price_numeric = (
                int(ew.edition_price_numeric) if ew.edition_price_numeric else None
            )

            work_rows.append(
                {
                    "number": str(ew.raw_cat_no) if ew.raw_cat_no else None,
                    "artist": ew.artist_name or "",
                    "honorifics": ew.artist_honorifics or None,
                    "title": ew.title or "",
                    "price_numeric": price_numeric,
                    "price_text": ew.price_text or "",
                    "edition_total": ew.edition_total,
                    "edition_price_numeric": edition_price_numeric,
                    "artwork": ew.artwork,
                    "medium": ew.medium or None,
                }
            )

        result.append(
            {
                "section_name": section.name,
                "position": section.position,
                "works": work_rows,
            }
        )

    return result


# ---------------------------------------------------------------------------
# InDesign Tagged Text helpers
# ---------------------------------------------------------------------------


def escape_for_mac_roman(text: str) -> str:
    """
    Replace any character that cannot be encoded in Mac Roman with the
    InDesign Tagged Text numeric Unicode escape <0x####>.
    The result is safe to .encode('mac_roman') without errors.
    """
    out = []
    for ch in text:
        try:
            ch.encode("mac_roman")
            out.append(ch)
        except (UnicodeEncodeError, UnicodeDecodeError):
            out.append(f"<0x{ord(ch):04X}>")
    return "".join(out)


# Opening punctuation that must not be left stranded at the end of a line.
_OPEN_PUNCT = set("'\"\u2018\u201c([")
# Closing punctuation that must not appear at the start of a line.
_CLOSE_PUNCT = set("'\",;:.!?)]\u2019\u201d")
# Dashes after which we do not want to break.
_NO_BREAK_AFTER = {"\u2013", "\u2014"}  # en-dash, em-dash


def _wrap_lines(text: str, max_chars: int) -> list:
    """
    Split *text* into lines of at most *max_chars* characters, always breaking
    at a space boundary and honouring punctuation attachment rules:

    - Opening quotes/brackets (', ", (, [, …) must not end a line.
    - Closing quotes/punctuation (',  ", ,, ;, :, …) must not start a line.
    - En-dash and em-dash must not immediately precede a line break.

    The space at the break point stays on the current line (trailing), so the
    next line never starts with a space.

    If no suitable space exists within the limit the line is hard-broken at
    max_chars with no space adjustment.
    """
    lines = []
    remaining = text

    while len(remaining) > max_chars:
        # Last space in [0, max_chars-1] so that remaining[:candidate+1] <= max_chars
        candidate = remaining.rfind(" ", 0, max_chars)

        if candidate < 0:
            # No space within limit — hard break
            lines.append(remaining[:max_chars])
            remaining = remaining[max_chars:]
            continue

        # Walk the candidate backwards until we find a clean break point
        for _ in range(max_chars):  # bounded to prevent infinite loop
            char_before = remaining[candidate - 1] if candidate > 0 else ""
            char_after = (
                remaining[candidate + 1] if candidate + 1 < len(remaining) else ""
            )
            bad = (
                char_before in _OPEN_PUNCT
                or char_before in _NO_BREAK_AFTER
                or char_after in _CLOSE_PUNCT
            )
            if not bad:
                break
            prev = remaining.rfind(" ", 0, candidate)
            if prev < 0:
                candidate = -1  # no clean break available
                break
            candidate = prev

        if candidate < 0:
            # Fallback: hard break
            lines.append(remaining[:max_chars])
            remaining = remaining[max_chars:]
        else:
            # Include the space on the current line; next line starts clean
            lines.append(remaining[: candidate + 1])
            remaining = remaining[candidate + 1 :]

    if remaining:
        lines.append(remaining)
    return lines


def _field_char_style(config: "ExportConfig", field: str) -> str:
    """Return the character style name for a given component field."""
    return {
        "work_number": config.cat_no_style,
        "artist": config.artist_style,
        "title": config.title_style,
        "edition": "",
        "artwork": config.artwork_style,
        "price": config.price_style,
        "medium": config.medium_style,
    }.get(field, "")


def _raw_text_for_field(field: str, w: dict) -> str:
    """Return the un-styled raw text for a component field from a work dict."""
    mapping = {
        "work_number": lambda: str(w["number"]) if w["number"] else "",
        "title": lambda: w["title"] or "",
        "medium": lambda: w["medium"] or "",
        "artwork": lambda: str(w["artwork"]) if w["artwork"] else "",
    }
    return mapping[field]() if field in mapping else ""


def _sep(name: str, entry_style: str = "") -> str:
    """Return the InDesign tagged-text string for a named separator."""
    if name == "none":
        return ""
    if name == "space":
        return " "
    if name == "tab":
        return "\t"
    if name == "right_tab":
        # InDesign Tagged Text has no escape for right-indent tab;
        # output a regular tab and let the paragraph's tab stop handle alignment.
        return "\t"
    if name == "soft_return":
        # InDesign tagged-text forced line break
        return "\n"
    if name == "hard_return":
        # Paragraph break — restart the entry style
        return f"\r<ParaStyle:{entry_style}>"
    return ""


def _cs(style: str, text: str) -> str:
    """Wrap text in an InDesign character style tag, or return plain text."""
    if not style or not text:
        return text
    return f"<CharStyle:{style}>{text}<CharStyle:>"


def _fmt_price(amount, config: "ExportConfig") -> str:
    """Format a numeric price amount using config separators and decimal places."""
    dp = config.decimal_places
    sep = config.thousands_separator
    n = float(amount)
    fixed = f"{n:.{dp}f}"
    # Apply thousands grouping then swap comma for chosen separator
    int_part, *dec_parts = fixed.split(".")
    grouped = ""
    for i, ch in enumerate(reversed(int_part)):
        if i and i % 3 == 0:
            grouped = sep + grouped
        grouped = ch + grouped
    result = grouped + ("." + dec_parts[0] if dec_parts else "")
    return f"{config.currency_symbol}{result}"


# ---------------------------------------------------------------------------
# Tagged Text (InDesign)
# ---------------------------------------------------------------------------


def render_import_as_tagged_text(
    import_id, db: Session, config: ExportConfig = DEFAULT_CONFIG, section_id=None
) -> str:
    """
    Render a full Import (or single section) as InDesign Tagged Text.
    Component order and separators are driven by config.components.
    """
    sections = _collect_export_data(import_id, db, section_id=section_id)
    lines = ["<ASCII-MAC>\r"]

    for section in sections:
        lines.append(f"<ParaStyle:{config.section_style}>{section['section_name']}")
        lines.append("\r")

        for w in section["works"]:
            # Pre-compute the value for every possible component field
            artist = _cs(config.artist_style, w["artist"])
            if w["honorifics"]:
                hon_text = (
                    w["honorifics"].lower()
                    if config.honorifics_lowercase
                    else w["honorifics"]
                )
                artist += " " + _cs(config.honorifics_style, hon_text)

            if w["price_numeric"]:
                raw_price = _fmt_price(w["price_numeric"], config)
            elif w["price_text"]:
                raw_price = w["price_text"]
            else:
                raw_price = ""

            edition_display = ""
            if w["edition_total"] and w["edition_price_numeric"]:
                inner = (
                    f"{config.edition_prefix} {w['edition_total']}"
                    f" at {_fmt_price(w['edition_price_numeric'], config)}"
                )
                edition_display = f"({inner})" if config.edition_brackets else inner
            elif w["edition_total"]:
                inner = f"{config.edition_prefix} {w['edition_total']}"
                edition_display = f"({inner})" if config.edition_brackets else inner

            comp_values: dict[str, str] = {
                "work_number": _cs(config.cat_no_style, w["number"] or ""),
                "artist": artist,
                "title": _cs(config.title_style, w["title"]),
                "edition": edition_display,
                "artwork": _cs(
                    config.artwork_style, str(w["artwork"]) if w["artwork"] else ""
                ),
                "price": _cs(config.price_style, raw_price),
                "medium": _cs(config.medium_style, w["medium"] or ""),
            }

            # Build entry from ordered components
            entry = f"<ParaStyle:{config.entry_style}>"
            entry += _sep(config.leading_separator, config.entry_style)

            enabled_comps = [c for c in config.components if c.enabled]
            skip_fields = set()

            for idx, comp in enumerate(enabled_comps):
                if comp.field in skip_fields:
                    continue

                val = comp_values.get(comp.field, "")

                # -- Wrapped / "end of first line" mode --
                should_wrap = (
                    comp.max_line_chars
                    and comp.next_component_position == "end_of_first_line"
                )
                if should_wrap:
                    raw = _raw_text_for_field(comp.field, w)
                    lines = _wrap_lines(raw, comp.max_line_chars) if raw else []
                    style = _field_char_style(config, comp.field)

                    if len(lines) <= 1:
                        # Title fits on one line — normal behaviour
                        if val:
                            entry += val
                            entry += _sep(comp.separator_after, config.entry_style)
                        elif not comp.omit_sep_when_empty:
                            entry += _sep(comp.separator_after, config.entry_style)
                    else:
                        # Multi-line: find the next enabled component (NC)
                        nc = (
                            enabled_comps[idx + 1]
                            if idx + 1 < len(enabled_comps)
                            else None
                        )
                        if nc:
                            skip_fields.add(nc.field)
                            nc_val = comp_values.get(nc.field, "")
                        else:
                            nc_val = ""

                        # First line of TC, then sep-after-TC, then NC
                        entry += _cs(style, lines[0])
                        entry += _sep(comp.separator_after, config.entry_style)
                        entry += nc_val  # NC inserted inline (empty string if no NC)

                        # Remaining lines of TC, all in one reopened char style block
                        rest = "\n".join(lines[1:])
                        if style:
                            entry += f"<CharStyle:{style}>\n{rest}<CharStyle:>"
                        else:
                            entry += "\n" + rest

                        # Sep-after-NC closes the whole block
                        if nc:
                            if nc_val:
                                entry += _sep(nc.separator_after, config.entry_style)
                            elif not nc.omit_sep_when_empty:
                                entry += _sep(nc.separator_after, config.entry_style)

                # -- Normal mode --
                else:
                    if val:
                        entry += val
                        entry += _sep(comp.separator_after, config.entry_style)
                    elif not comp.omit_sep_when_empty:
                        entry += _sep(comp.separator_after, config.entry_style)

            entry += _sep(config.trailing_separator, config.entry_style)

            lines.append(entry)
            lines.append("\r")

        lines.append("\r")

    return "".join(lines)


# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------


def render_import_as_json(import_id, db: Session) -> str:
    """
    Render a full Import as structured JSON.
    """
    sections = _collect_export_data(import_id, db)
    return json.dumps({"sections": sections}, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# XML export
# ---------------------------------------------------------------------------


def render_import_as_xml(import_id, db: Session) -> str:
    """
    Render a full Import as XML.

    Structure:
    <catalogue>
      <section name="..." position="...">
        <work>
          <number>...</number>
          <artist>...</artist>
          <honorifics>...</honorifics>
          <title>...</title>
          <price_numeric>...</price_numeric>
          <price_text>...</price_text>
          <edition_total>...</edition_total>
          <edition_price_numeric>...</edition_price_numeric>
          <medium>...</medium>
        </work>
      </section>
    </catalogue>
    """
    sections = _collect_export_data(import_id, db)

    root = ET.Element("catalogue")

    for section in sections:
        sec_el = ET.SubElement(root, "section")
        sec_el.set("name", section["section_name"])
        sec_el.set("position", str(section["position"]))

        for w in section["works"]:
            work_el = ET.SubElement(sec_el, "work")

            for tag, value in [
                ("number", w["number"]),
                ("artist", w["artist"]),
                ("honorifics", w["honorifics"]),
                ("title", w["title"]),
                (
                    "price_numeric",
                    str(w["price_numeric"]) if w["price_numeric"] is not None else None,
                ),
                ("price_text", w["price_text"]),
                (
                    "edition_total",
                    str(w["edition_total"]) if w["edition_total"] is not None else None,
                ),
                (
                    "edition_price_numeric",
                    (
                        str(w["edition_price_numeric"])
                        if w["edition_price_numeric"] is not None
                        else None
                    ),
                ),
                ("medium", w["medium"]),
            ]:
                el = ET.SubElement(work_el, tag)
                el.text = value if value is not None else ""

    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode", xml_declaration=False)


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

CSV_COLUMNS = [
    "section",
    "number",
    "artist",
    "honorifics",
    "title",
    "price_numeric",
    "price_text",
    "edition_total",
    "edition_price_numeric",
    "medium",
]


def render_import_as_csv(import_id, db: Session) -> str:
    """
    Render a full Import as CSV.

    Flat structure – one row per work with section name as a column.
    """
    sections = _collect_export_data(import_id, db)

    output = io.StringIO()
    writer = csv.DictWriter(
        output, fieldnames=CSV_COLUMNS, lineterminator="\n", extrasaction="ignore"
    )
    writer.writeheader()

    for section in sections:
        for w in section["works"]:
            writer.writerow(
                {
                    "section": section["section_name"],
                    "number": w["number"] or "",
                    "artist": w["artist"],
                    "honorifics": w["honorifics"] or "",
                    "title": w["title"],
                    "price_numeric": (
                        w["price_numeric"] if w["price_numeric"] is not None else ""
                    ),
                    "price_text": w["price_text"],
                    "edition_total": (
                        w["edition_total"] if w["edition_total"] is not None else ""
                    ),
                    "edition_price_numeric": (
                        w["edition_price_numeric"]
                        if w["edition_price_numeric"] is not None
                        else ""
                    ),
                    "medium": w["medium"] or "",
                }
            )

    return output.getvalue()
