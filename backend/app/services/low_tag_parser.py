"""Parse corrected List of Works InDesign Tagged Text back into structured
field display-strings, for diffing against the database (the source of truth).

See ``docs/low-tag-reimport-diff-roadmap.md`` for the design and rationale.

Detection-only: we recover each field's *display string* (what appears in
print), keyed by catalogue number and grouped by section. The diff compares
display strings — which is what both the LOW and the LPG care about — so the
parser never needs to invert £-formatting or edition syntax back into numbers.

Parsing strategy
----------------
- Split on CR into paragraphs; keep only paragraphs whose ``<ParaStyle:…>`` is
  the configured entry or section style (an allowlist, not a denylist — foreign
  design content is never even considered).
- Track the current section from section-style paragraphs.
- One entry-style paragraph == one entry. (Both current templates lay an entry
  out as a single paragraph using soft returns, not hard returns. Hard-return
  continuation merging is a documented future enhancement.)
- Within an entry, collect ``<CharStyle:NAME>…<CharStyle:>`` spans and group
  them by style in document order. Concatenate same-style fragments without
  inserting separators, then delete soft returns. This is lossless against line
  wrapping and price interleaving because the renderer only ever *splits* text
  (it keeps the breaking space) — it never injects characters.
- Character-style collisions (e.g. the 2026 template styles both the work
  number and the title as "Work Number/Name") are resolved by component order:
  the first span of a shared style maps to the earlier component, the rest to
  the later one (only the last colliding component may be wrapped/multi-span).

Tag dialects: our renderer emits the verbose forms ``<ParaStyle:Name>`` /
``<CharStyle:Name>…<CharStyle:>`` with CR (``\\r``) paragraph breaks. A real
InDesign re-export uses the short forms ``<pstyle:Name>`` / ``<cstyle:Name>…
<cstyle:>`` with line-feed paragraph breaks (and a preamble of ``<vsn:>`` /
``<dps:>`` / ``<dcs:>`` style definitions, which the paragraph allowlist
discards). The parser handles both. (How InDesign represents a *forced line
break* within a paragraph in the short dialect is still to be confirmed against
a real wrapped LOW file — see the roadmap's open questions.)
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from backend.app.services.export_renderer import ExportConfig, DEFAULT_CONFIG

# Match both the verbose (our renderer) and short (InDesign) tag dialects.
_PARA_RE = re.compile(r"^\s*<(?:ParaStyle|pstyle):([^>]*)>")
_SPAN_RE = re.compile(
    r"<(?:CharStyle|cstyle):([^>]+)>(.*?)<(?:CharStyle|cstyle):>", re.DOTALL
)
_INDESIGN_HINT = re.compile(r"<(?:pstyle|cstyle):")
_HEX_RE = re.compile(r"<0x([0-9A-Fa-f]+)>")
_TAG_RE = re.compile(r"<[^>]*>")
# InDesign escapes special characters with a backslash, in both content and
# style names (e.g. "Work Number\/Name", "\<", "\\").
_BACKSLASH_RE = re.compile(r"\\(.)", re.DOTALL)

# Field name -> the ExportConfig attribute that holds its character-style name.
_FIELD_STYLE_ATTRS: dict[str, str] = {
    "work_number": "cat_no_style",
    "artist": "artist_style",
    "honorifics": "honorifics_style",
    "title": "title_style",
    "price": "price_style",
    "medium": "medium_style",
    "artwork": "artwork_style",
    "edition": "edition_style",
}


@dataclass
class ParsedEntry:
    """One catalogue entry recovered from the tags."""

    cat_no: str
    section_name: str
    fields: dict[str, str]  # field name -> display string (only fields present)
    paragraph_index: int


def _decode(s: str) -> str:
    """Undo InDesign escaping: backslash escapes then ``<0x####>`` numeric
    escapes (the latter incl. ``<0x000A>`` forced line breaks → ``\\n``)."""
    s = _BACKSLASH_RE.sub(r"\1", s)
    return _HEX_RE.sub(lambda m: chr(int(m.group(1), 16)), s)


def _clean(value: str) -> str:
    """Decode escapes, drop soft returns, NFC-normalise a field value.

    Order matters: decode ``<0x000A>`` to ``\\n`` *before* deleting newlines, so
    both literal soft returns and escaped ones are removed. Deleting ``\\n`` is
    the exact inverse of the renderer's wrapping because the breaking space is
    kept on the preceding line.
    """
    return unicodedata.normalize("NFC", _decode(value).replace("\n", ""))


def _unescape_name(name: str) -> str:
    """Style names are backslash-escaped by InDesign (e.g. ``Work Number\\/Name``)."""
    return _BACKSLASH_RE.sub(r"\1", name)


def enabled_field_order(config: ExportConfig) -> list[str]:
    """Field names in the order the renderer emits them, with honorifics placed
    immediately after artist (the renderer appends it to the artist value)."""
    order: list[str] = []
    for comp in config.components:
        if not comp.enabled:
            continue
        order.append(comp.field)
        if comp.field == "artist":
            order.append("honorifics")
    return order


def recoverable_fields(config: ExportConfig) -> list[str]:
    """Enabled fields that carry a non-empty character style — i.e. the fields a
    parse can actually isolate (and therefore the only fields the LOW diff can
    check)."""
    return [
        f
        for f in enabled_field_order(config)
        if getattr(config, _FIELD_STYLE_ATTRS[f], "")
    ]


def _style_to_fields(config: ExportConfig) -> dict[str, list[str]]:
    """Map each character-style NAME to the fields that use it, in component
    order. Empty style names are skipped (unrecoverable)."""
    mapping: dict[str, list[str]] = {}
    for fld in enabled_field_order(config):
        style = getattr(config, _FIELD_STYLE_ATTRS[fld], "")
        if not style:
            continue
        mapping.setdefault(style, []).append(fld)
    return mapping


def _assign_spans(
    spans: list[tuple[str, str]], style_fields: dict[str, list[str]]
) -> dict[str, str]:
    """Assign ordered ``(style, value)`` spans within one entry to fields.

    For a style used by a single field, all its spans concatenate into that
    field. For a colliding style used by N fields, the first N-1 spans map to
    the first N-1 fields (one each) and any remaining spans concatenate into the
    last field (the only one that may be wrapped / multi-fragment).
    """
    by_style: dict[str, list[str]] = {}
    for style, value in spans:
        by_style.setdefault(_unescape_name(style), []).append(value)

    out: dict[str, str] = {}
    for style, values in by_style.items():
        fields = style_fields.get(style)
        if not fields:
            continue  # a style we don't track
        if len(fields) == 1:
            out[fields[0]] = _clean("".join(values))
            continue
        for i, fld in enumerate(fields[:-1]):
            if i < len(values):
                out[fld] = _clean(values[i])
        rest = values[len(fields) - 1 :]
        if rest:
            out[fields[-1]] = _clean("".join(rest))
    return out


def parse_low_tags(
    text: str, config: ExportConfig = DEFAULT_CONFIG
) -> list[ParsedEntry]:
    """Parse a List of Works Tagged Text export into a list of ``ParsedEntry``.

    ``config`` must be the ExportConfig that produced the file (it supplies the
    paragraph/character style-name allowlist and the component order).
    """
    style_fields = _style_to_fields(config)
    entries: list[ParsedEntry] = []
    current_section = ""

    # Native dialect uses CR for paragraphs and LF for soft returns (kept inside
    # spans and removed by _clean). The InDesign short dialect uses line breaks
    # for paragraphs, so split on either there.
    if _INDESIGN_HINT.search(text):
        paragraphs = re.split(r"[\r\n]+", text)
    else:
        paragraphs = text.split("\r")

    for idx, para in enumerate(paragraphs):
        m = _PARA_RE.match(para)
        if not m:
            continue  # header, blank separator paragraphs, etc.
        para_style = m.group(1)
        body = para[m.end() :]

        if para_style == config.section_style:
            # Decode escapes first, then strip any residual tags, so a room name
            # containing escaped characters isn't lost with the tags.
            name = _TAG_RE.sub("", _decode(body)).replace("\n", " ")
            current_section = unicodedata.normalize("NFC", name).strip()
            continue
        if para_style != config.entry_style:
            continue  # not on the paragraph allowlist

        spans = _SPAN_RE.findall(body)
        if not spans:
            continue
        fields = _assign_spans(spans, style_fields)
        cat_no = (fields.get("work_number") or "").strip()
        if not cat_no:
            continue  # belt-and-braces: a real entry yields a cat number
        fields["work_number"] = cat_no
        entries.append(
            ParsedEntry(
                cat_no=cat_no,
                section_name=current_section,
                fields=fields,
                paragraph_index=idx,
            )
        )

    return entries
