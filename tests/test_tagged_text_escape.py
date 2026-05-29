"""Tests for the InDesign Tagged Text metacharacter escape and its parser
inverse.

The trigger: work #263 in the 2026 catalogue has the title
``ENTANGLEMENT (200) INTERACTION > INTRA-ACTION``. The literal ``>`` is a
reserved character in Tagged Text grammar and InDesign rejects the whole
file with
``A closing tag symbol > was found without the corresponding opening tag``.

These tests pin three behaviours:

1. The renderer escapes ``\\``, ``<``, ``>`` in every user-supplied field
   value and in section headings (both inline and wrapped paths).
2. The parser's single-pass decoder unescapes them, including when escapes
   are mixed with inline formatting tags InDesign may have left behind.
3. Render → parse round-trips. Without this, every escaped export would
   produce a wall of false-positive findings in the LOW reconcile.
"""

from types import SimpleNamespace

from backend.app.services.export_renderer import (
    ComponentConfig,
    ExportConfig,
    escape_tagged_text_chars,
    render_import_as_tagged_text,
)
from backend.app.services.index_renderer import (
    ArtistExportEntry,
    IndexExportConfig,
    render_index_tagged_text,
)
from backend.app.services.low_tag_parser import (
    _clean,
    _decode_content,
    parse_low_tags,
)

# ---------------------------------------------------------------------------
# Minimal fakes (mirrors tests/test_renderer.py)
# ---------------------------------------------------------------------------


class _FakeQuery:
    def __init__(self, results):
        self._results = results

    def filter(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def all(self):
        return self._results


class _FakeSession:
    def __init__(self, sections, works, overrides=None):
        self.sections = sections
        self.works = works
        self.overrides = overrides or []

    def query(self, model):
        return {
            "Section": _FakeQuery(self.sections),
            "Work": _FakeQuery(self.works),
            "WorkOverride": _FakeQuery(self.overrides),
        }.get(model.__name__, _FakeQuery([]))


def _section(id, name, position):
    return SimpleNamespace(id=id, import_id="imp1", name=name, position=position)


def _work(section_id, pos, cat_no, **kw):
    base = dict(
        id=f"w{cat_no}",
        raw_cat_no=cat_no,
        artist_name="",
        artist_honorifics=None,
        title="",
        price_numeric=None,
        price_text="",
        edition_total=None,
        edition_price_numeric=None,
        artwork=None,
        medium=None,
        section_id=section_id,
        position_in_section=pos,
        include_in_export=True,
    )
    base.update(kw)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# escape_tagged_text_chars — the helper itself
# ---------------------------------------------------------------------------


def test_escape_helper_handles_each_metacharacter():
    assert escape_tagged_text_chars("a < b") == "a \\< b"
    assert escape_tagged_text_chars("a > b") == "a \\> b"
    assert escape_tagged_text_chars("path\\file") == "path\\\\file"


def test_escape_helper_order_does_not_double_escape():
    """Backslash must be doubled BEFORE the angle brackets are escaped,
    otherwise the inserted backslash from ``<`` → ``\\<`` would be doubled
    on a second pass, breaking the parser."""
    assert escape_tagged_text_chars("<>") == "\\<\\>"
    # A pre-existing backslash followed by an angle bracket must not be
    # absorbed: it stays a literal backslash plus an escaped bracket.
    assert escape_tagged_text_chars("a\\<b") == "a\\\\\\<b"


def test_escape_helper_passthrough():
    assert escape_tagged_text_chars("") == ""
    assert escape_tagged_text_chars(None) is None
    assert escape_tagged_text_chars("Plain title — no metas") == "Plain title — no metas"


# ---------------------------------------------------------------------------
# Renderer — inline path (no wrap)
# ---------------------------------------------------------------------------


def _render_one_work(title, **work_kw):
    section = _section("s1", "Room", 1)
    work = _work("s1", 1, 1, title=title, artist_name="A", **work_kw)
    return render_import_as_tagged_text("imp1", _FakeSession([section], [work]))


def test_inline_render_escapes_gt_in_title():
    out = _render_one_work("INTERACTION > INTRA-ACTION")
    assert "INTERACTION \\> INTRA-ACTION" in out
    # And the unescaped form must not survive — that's the InDesign-breaking byte.
    assert "INTERACTION > INTRA-ACTION" not in out


def test_inline_render_escapes_lt_in_title():
    out = _render_one_work("Made with <fire>")
    assert "Made with \\<fire\\>" in out


def test_inline_render_escapes_backslash_in_title():
    out = _render_one_work("path\\to\\work")
    # Each \\ in the input becomes \\\\ in the output (one literal backslash → two).
    assert "path\\\\to\\\\work" in out


def test_inline_render_escapes_artist_and_medium():
    section = _section("s1", "Room", 1)
    work = _work(
        "s1", 1, 1,
        artist_name="A & <B>",
        title="t",
        medium="oil on <canvas>",
    )
    out = render_import_as_tagged_text("imp1", _FakeSession([section], [work]))
    assert "A & \\<B\\>" in out
    assert "oil on \\<canvas\\>" in out


def test_render_escapes_section_name():
    section = _section("s1", "Gallery < 1 >", 1)
    work = _work("s1", 1, 1, artist_name="A", title="t")
    out = render_import_as_tagged_text("imp1", _FakeSession([section], [work]))
    assert "<ParaStyle:SectionTitle>Gallery \\< 1 \\>" in out


# ---------------------------------------------------------------------------
# Renderer — wrapped path (the direct-emission bypasses)
# ---------------------------------------------------------------------------


def test_wrapped_title_escapes_per_line():
    """The wrapped-mode branch joins lines with ``\\n`` and constructs a single
    ``<CharStyle:…>…<CharStyle:>`` block directly, bypassing ``_cs``. Each line
    must still be escaped — and the parser must still recover the original
    title from the wrapped output."""
    config = ExportConfig(
        components=[
            ComponentConfig("work_number", "tab"),
            ComponentConfig("title", "none", max_line_chars=12, balance_lines=False),
        ],
    )
    title = "first > line second > line"
    out = _render_one_work_with_config(title, config)
    # Both ``>`` characters must be escaped wherever they end up in the wrap.
    assert " > " not in out
    assert "\\>" in out
    # Parsing the wrapped output reconstructs the original title — the wrap
    # produces multiple soft-return-separated lines inside one styled run,
    # which the parser un-wraps by deleting the soft returns.
    parsed = parse_low_tags(out, config)
    assert parsed[0].fields["title"] == title


def test_wrapped_title_end_of_first_line_escapes_per_line():
    """The end_of_first_line branch is the one that 2026's template uses (price
    interleaved between wrapped title lines). Both halves of the title must end
    up escaped — that's the actual #263 layout."""
    config = ExportConfig(
        cat_no_style="Work Number/Name",
        title_style="Work Number/Name",
        price_style="Work Price",
        components=[
            ComponentConfig("work_number", "tab", omit_sep_when_empty=False),
            ComponentConfig(
                "title", "tab", max_line_chars=22, balance_lines=True,
                next_component_position="end_of_first_line",
            ),
            ComponentConfig("price", "none", omit_sep_when_empty=False),
        ],
    )
    out = _render_one_work_with_config(
        "ENTANGLEMENT (200) INTERACTION > INTRA-ACTION", config, price_numeric=2400,
    )
    # Literal ``>`` from the title must never make it to the file body.
    # Allow the ``>`` inside ``<ParaStyle:…>``, ``<CharStyle:…>``, ``<ASCII-MAC>``.
    assert _has_no_unescaped_gt_in_content(out), (
        f"unescaped > in body of:\n{out}"
    )
    # And the escape sequence is present.
    assert "\\>" in out


def _render_one_work_with_config(title, config, **work_kw):
    section = _section("s1", "Room", 1)
    work = _work("s1", 1, 1, title=title, artist_name="A", **work_kw)
    return render_import_as_tagged_text("imp1", _FakeSession([section], [work]), config)


def _has_no_unescaped_gt_in_content(out):
    """Walk the rendered text once; any ``>`` that isn't (a) closing a Tagged
    Text tag we opened, or (b) immediately preceded by an escaping backslash,
    is the bug we're guarding against."""
    i = 0
    n = len(out)
    while i < n:
        ch = out[i]
        if ch == "<":
            # Skip to the matching '>' — that '>' is a tag terminator we wrote.
            j = out.find(">", i + 1)
            if j < 0:
                return False
            i = j + 1
            continue
        if ch == ">":
            # In content, outside a tag, and not preceded by an unescaped '\\'.
            if i == 0 or out[i - 1] != "\\":
                return False
        i += 1
    return True


# ---------------------------------------------------------------------------
# Parser — decoder behaviour
# ---------------------------------------------------------------------------


def test_decode_content_unescapes_backslash_metacharacters():
    assert _decode_content("a \\< b \\> c") == "a < b > c"
    assert _decode_content("path\\\\file") == "path\\file"


def test_decode_content_strips_inline_tags_but_preserves_escaped_brackets():
    """The original two-pass implementation (strip-tags then unescape) would
    greedily consume the ``<x\\>`` slice and lose the title body. The
    single-pass walker keeps escaped brackets as literals first, then drops
    the inline tag."""
    assert (
        _decode_content("Hello \\<world\\> <ccase:upper>X<ccase:>")
        == "Hello <world> X"
    )


def test_decode_content_hex_escape_still_works():
    assert _decode_content("M<0x2019>Coul") == "M’Coul"
    # Hex inside an otherwise-escaped run — the cases compose.
    assert (
        _decode_content("\\<a<0x2014>b\\>") == "<a—b>"
    )


def test_clean_strips_control_chars_after_decoding():
    # Soft return arrives as <0x000A> → \n; _clean drops it.
    assert _clean("line one<0x000A>line two") == "line oneline two"
    # And backslash-escaped angle brackets survive.
    assert _clean("A \\<B\\> C") == "A <B> C"


# ---------------------------------------------------------------------------
# Round-trip: render then parse
# ---------------------------------------------------------------------------


def test_roundtrip_title_with_metacharacters():
    """The exact #263 shape: long title with a literal ``>`` mid-string, wrap +
    interleaved price. Renders to a valid-looking file and parses straight back
    to the original title."""
    config = ExportConfig(
        cat_no_style="Work Number/Name",
        title_style="Work Number/Name",
        price_style="Work Price",
        components=[
            ComponentConfig("work_number", "tab", omit_sep_when_empty=False),
            ComponentConfig(
                "title", "tab", max_line_chars=22, balance_lines=True,
                next_component_position="end_of_first_line",
            ),
            ComponentConfig("price", "none", omit_sep_when_empty=False),
        ],
    )
    title = "ENTANGLEMENT (200) INTERACTION > INTRA-ACTION"
    section = _section("s1", "Room", 1)
    work = _work("s1", 1, 263, title=title, artist_name="A", price_numeric=2400)
    db = _FakeSession([section], [work])

    text = render_import_as_tagged_text("imp1", db, config)
    parsed = parse_low_tags(text, config)

    assert len(parsed) == 1
    assert parsed[0].cat_no == "263"
    assert parsed[0].fields["title"] == title


def test_roundtrip_inline_with_all_three_metacharacters():
    title = "A < B > C and a backslash \\ too"
    section = _section("s1", "Room", 1)
    work = _work("s1", 1, 1, title=title, artist_name="A")
    db = _FakeSession([section], [work])

    text = render_import_as_tagged_text("imp1", db)
    parsed = parse_low_tags(text, ExportConfig())
    assert parsed[0].fields["title"] == title


def test_roundtrip_preserves_section_name_metacharacters():
    section = _section("s1", "Gallery <1>", 1)
    work = _work("s1", 1, 1, title="t", artist_name="A")
    db = _FakeSession([section], [work])
    text = render_import_as_tagged_text("imp1", db)
    parsed = parse_low_tags(text, ExportConfig())
    assert parsed[0].section_name == "Gallery <1>"


# ---------------------------------------------------------------------------
# Index renderer
# ---------------------------------------------------------------------------


def _index_entry(**kw):
    base = dict(
        title=None,
        first_name=None,
        last_name=None,
        quals=None,
        company=None,
        artist2_first_name=None,
        artist2_last_name=None,
        artist2_quals=None,
        artist3_first_name=None,
        artist3_last_name=None,
        artist3_quals=None,
        artist1_ra_styled=False,
        artist2_ra_styled=False,
        artist3_ra_styled=False,
        artist2_shared_surname=False,
        artist3_shared_surname=False,
        is_ra_member=False,
        is_company=False,
        sort_key="z",
        courtesy=None,
        cat_nos=[1],
    )
    base.update(kw)
    return ArtistExportEntry(**base)


def test_index_renderer_escapes_surname_and_first_name():
    entry = _index_entry(
        first_name="Mary <Anne>",
        last_name="O'Brien & Smith",
        sort_key="o",
    )
    out = render_index_tagged_text([entry], IndexExportConfig())
    assert "Mary \\<Anne\\>" in out
    assert "<Anne>" not in out  # no unescaped form leaks through


def test_index_renderer_escapes_company_and_quals():
    entry = _index_entry(
        last_name="Studio <X>",
        company="Studio <X>",
        quals="Hon < RA >",
        is_company=True,
        sort_key="s",
    )
    out = render_index_tagged_text([entry], IndexExportConfig())
    assert "Studio \\<X\\>" in out
    # Default config lowercases quals — verify the escape survives lowercasing
    # (backslashes are stable across .lower()).
    assert "hon \\< ra \\>" in out


def test_index_renderer_does_not_break_letter_grouping():
    """``sort_key`` is intentionally not escaped — letter grouping looks at the
    first character to decide the bucket. Verify a normal sort_key still groups."""
    a = _index_entry(first_name="A", last_name="Adams", sort_key="adams a")
    b = _index_entry(first_name="B", last_name="Brown", sort_key="brown b")
    out = render_index_tagged_text([a, b], IndexExportConfig())
    # Both entries make it through and the separator between letter groups appears.
    assert "Adams" in out
    assert "Brown" in out
