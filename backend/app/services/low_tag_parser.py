"""Parse corrected List of Works InDesign Tagged Text back into structured
field display-strings, for diffing against the database (the source of truth).

See ``docs/reconcile.md`` for the design and rationale.

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

from backend.app.services.export_renderer import DEFAULT_CONFIG, ExportConfig

# Match both the verbose (our renderer) and short (InDesign) tag dialects.
_PARA_RE = re.compile(r"^\s*<(?:ParaStyle|pstyle):([^>]*)>")
_SPAN_RE = re.compile(r"<(?:CharStyle|cstyle):([^>]+)>(.*?)<(?:CharStyle|cstyle):>", re.DOTALL)
_INDESIGN_HINT = re.compile(r"<(?:pstyle|cstyle):")
_HEX_RE = re.compile(r"<0x([0-9A-Fa-f]+)>")
# InDesign escapes special characters with a backslash, in both content and
# style names (e.g. "Work Number\/Name", "\<", "\\"). Used only for style-name
# unescape; content is decoded by ``_decode_content`` which handles backslash
# escapes and inline-tag stripping together (the two cannot be applied as
# separate regex passes — see ``_decode_content``'s docstring).
_BACKSLASH_RE = re.compile(r"\\(.)", re.DOTALL)
_HEX_ONLY_RE = re.compile(r"^0x([0-9A-Fa-f]+)$")
# Control characters InDesign embeds (soft returns, \x08/\x03 around headings).
_CONTROL_RE = re.compile(r"[\x00-\x1f]")
# A catalogue-number range in gallery titles, e.g. "works 200-286" or
# "works 287-431." — consume an optional trailing full stop too (it's the
# annotation's punctuation, not part of the gallery name).
_WORKS_RANGE_RE = re.compile(r"\bworks?\s+\d+\s*[-–—]\s*\d+\s*\.?", re.IGNORECASE)

# Field name -> the ExportConfig attribute that holds its character-style name.
_FIELD_STYLE_ATTRS: dict[str, str] = {
    "work_number": "cat_no_style",
    "artist": "artist_style",
    "honorifics": "honorifics_style",
    "title": "title_style",
    "title_cased": "title_cased_style",
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


def _decode_content(value: str) -> str:
    """Decode the body of a styled span (or a section-heading paragraph).

    Walks the string left-to-right and resolves the three things that can
    appear in tagged-text content, in one pass:

    - ``\\X`` is a backslash-escaped literal — emits ``X`` verbatim. Covers
      the renderer's ``\\<`` / ``\\>`` / ``\\\\`` escapes (without which a
      title like ``A > B`` breaks InDesign import).
    - ``<0x####>`` is a numeric Unicode escape — emits the character.
      Forced line breaks come through as ``<0x000A>`` → ``\\n`` and are
      stripped later by the caller's control-char pass.
    - Any other ``<…>`` is an inline formatting tag InDesign may emit inside
      a styled run (``<ccase:upper>``, ``<cs:…>``, kerning…) — discarded.

    The single pass is load-bearing. A regex sequence "unescape backslashes,
    then strip tags" would turn ``\\<x\\>`` into ``<x>`` and then delete it.
    "Strip tags, then unescape backslashes" lets the tag regex greedily
    consume ``<x\\>`` because the backslash doesn't break the ``[^>]*``
    match. Neither order is correct; the walker treats ``\\<`` as a literal
    before considering ``<`` as a tag opener.
    """
    out: list[str] = []
    i = 0
    n = len(value)
    while i < n:
        ch = value[i]
        if ch == "\\" and i + 1 < n:
            out.append(value[i + 1])
            i += 2
            continue
        if ch == "<":
            j = value.find(">", i + 1)
            if j < 0:
                # Unterminated angle bracket — keep as literal so downstream
                # comparison shows it rather than truncating the field.
                out.append(ch)
                i += 1
                continue
            tag_body = value[i + 1 : j]
            hex_match = _HEX_ONLY_RE.match(tag_body)
            if hex_match:
                out.append(chr(int(hex_match.group(1), 16)))
            # else: a foreign inline tag — drop it entirely.
            i = j + 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _decode(s: str) -> str:
    """Decode a paragraph body for non-clean uses (section heading prep)."""
    return _decode_content(s)


def _post_decode(value: str) -> str:
    """Final cleanup applied AFTER ``_decode_content`` has run: strip control
    characters (soft returns arrive as ``<0x000A>``→``\\n`` and are removed
    here — the breaking space was kept on the previous line by the renderer,
    so this inverts the wrap), and NFC-normalise so composed/decomposed forms
    compare equal in the diff."""
    return unicodedata.normalize("NFC", _CONTROL_RE.sub("", value))


def _clean(value: str) -> str:
    """Recover a field value from a raw (not-yet-decoded) span body.

    Full pipeline: decode escapes/strip inline tags, then post-decode cleanup.
    NOT idempotent — call this on each raw value exactly once.
    """
    return _post_decode(_decode_content(value))


def _unescape_name(name: str) -> str:
    """Style names are backslash-escaped by InDesign (e.g. ``Work Number\\/Name``).

    Style names never contain numeric escapes or inline tags, so the simple
    backslash unescape is sufficient — and we deliberately don't use
    ``_decode_content`` here because we want a literal ``<`` inside a style
    name (vanishingly unlikely, but possible) to survive."""
    return _BACKSLASH_RE.sub(r"\1", name)


def _strip_inline(value: str) -> str:
    """Decode a span value before splitting colliding runs on tab.

    Identical to ``_decode_content``: same single-pass walker, just named for
    intent at the callsite (``_assign_spans`` needs values decoded but with
    ``\\t`` characters intact so it can split on them — the post-decode
    cleanup that strips control chars happens via ``_post_decode`` on each
    piece *after* the split).
    """
    return _decode_content(value)


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
    return [f for f in enabled_field_order(config) if getattr(config, _FIELD_STYLE_ATTRS[f], "")]


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
        by_style.setdefault(_unescape_name(style), []).append(_strip_inline(value))

    out: dict[str, str] = {}
    for style, values in by_style.items():
        fields = style_fields.get(style)
        if not fields:
            continue  # a style we don't track
        if len(fields) == 1:
            # ``values`` are already _decode_content'd via _strip_inline above.
            # Call _post_decode (control-strip + NFC) only — running the full
            # _clean here would walk the decoded text a second time and either
            # double-strip (`\\<x\\>` → `<x>` → ``) or double-unescape (`\\\\`
            # → `\\` → ``X)`` for `\\X`).
            out[fields[0]] = _post_decode("".join(values))
            continue
        # Colliding style used by several components. They may arrive as separate
        # spans OR as one span with the inter-component tab(s) embedded (InDesign
        # collapses adjacent runs of the same character style). Split on tab,
        # post-decode each piece, and keep only those with real content — so ANY
        # local modification (inline tag, control char, stray whitespace),
        # wherever it sits in the run, is ignored and the cat number is the
        # first real piece.
        pieces: list[str] = []
        for v in values:
            for p in v.split("\t"):
                c = _post_decode(p)
                if c.strip():
                    pieces.append(c)
        for i, fld in enumerate(fields[:-1]):
            if i < len(pieces):
                out[fld] = pieces[i]
        rest = pieces[len(fields) - 1 :]
        if rest:
            out[fields[-1]] = "".join(rest)
    return out


def parse_low_tags(text: str, config: ExportConfig = DEFAULT_CONFIG) -> list[ParsedEntry]:
    """Parse a List of Works Tagged Text export into a list of ``ParsedEntry``.

    ``config`` must be the ExportConfig that produced the file (it supplies the
    paragraph/character style-name allowlist and the component order).
    """
    style_fields = _style_to_fields(config)
    # Paragraph styles that denote a gallery/section heading. A LoW worked in
    # InDesign may use several (e.g. "Gallery 2 deck small" and "Gallery Roman");
    # config.section_styles lists the equivalents beyond the primary one.
    section_styles = {config.section_style, *getattr(config, "section_styles", [])}
    entries: list[ParsedEntry] = []
    current_section = ""

    # Split into paragraphs. The InDesign short dialect marks every paragraph
    # with <pstyle:…>, so split on that marker — a gallery heading and the
    # following entry can share one physical line (separated by special break
    # chars, not a newline), and splitting on line breaks alone loses those
    # entries. The native (renderer) dialect uses CR per paragraph.
    if _INDESIGN_HINT.search(text):
        paragraphs = re.split(r"(?=<pstyle:)", text)
    else:
        paragraphs = text.split("\r")

    for idx, para in enumerate(paragraphs):
        m = _PARA_RE.match(para)
        if not m:
            continue  # header, blank separator paragraphs, etc.
        para_style = m.group(1)
        body = para[m.end() :]

        if para_style in section_styles:
            # Decode content escapes + strip inline tags in one pass, replace
            # control chars (incl. soft returns from ``<0x000A>``) with spaces,
            # drop any "works N-NN" catalogue-range suffix, collapse whitespace.
            # ``_decode`` is the single-pass walker, so an escaped ``\<`` in
            # the gallery name survives as a literal ``<`` rather than being
            # consumed as a tag opener.
            name = _decode(body)
            name = _CONTROL_RE.sub(" ", name)
            name = _WORKS_RANGE_RE.sub("", name)
            name = re.sub(r"\s+", " ", name)
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
