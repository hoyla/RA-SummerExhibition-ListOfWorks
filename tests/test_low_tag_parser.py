"""Tests for the corrected-LOW Tagged Text parser and the round-trip identity
gate (export -> parse -> compare against the resolved DB display strings).

The round-trip gate is the feasibility check for the whole LOW -> LPG
reconciliation feature: if an *unmodified* exported file does not parse straight
back to the values it was rendered from, every later diff is false positives.
"""

from types import SimpleNamespace

from backend.app.services.export_renderer import (
    render_import_as_tagged_text,
    _collect_export_data,
    ExportConfig,
    ComponentConfig,
)
from backend.app.services.low_tag_parser import parse_low_tags
from backend.app.services.low_diff import work_display_fields


# ---------------------------------------------------------------------------
# Minimal in-memory session (mirrors tests/test_renderer.py)
# ---------------------------------------------------------------------------


class FakeQuery:
    def __init__(self, results):
        self._results = results

    def filter(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def all(self):
        return self._results


class FakeSession:
    def __init__(self, sections, works, overrides=None):
        self.sections = sections
        self.works = works
        self.overrides = overrides or []

    def query(self, model):
        return {
            "Section": FakeQuery(self.sections),
            "Work": FakeQuery(self.works),
            "WorkOverride": FakeQuery(self.overrides),
        }.get(model.__name__, FakeQuery([]))


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


def _config_2026() -> ExportConfig:
    """Faithful reconstruction of seed_templates/list-of-works-2026.json:
    shared cat-no/title style ("Work Number/Name"), title wrap with price
    interleaved (end_of_first_line), multi-line medium, lowercase honorifics."""
    return ExportConfig(
        entry_style="Title No Nest",
        section_style="Gallery 2 deck small",
        cat_no_style="Work Number/Name",
        title_style="Work Number/Name",  # deliberate collision with cat-no
        price_style="Work Price",
        medium_style="Work Medium",
        artist_style="Artist",
        artwork_style="Artwork",
        honorifics_style="Artist honorifics",
        edition_style="Work Edition",
        honorifics_lowercase=True,
        leading_separator="tab",
        trailing_separator="none",
        section_separator="column_break",
        section_separator_style="Spacer",
        final_sep_from_last_component=True,
        components=[
            ComponentConfig("work_number", "tab", omit_sep_when_empty=False),
            ComponentConfig(
                "title",
                "tab",
                omit_sep_when_empty=False,
                max_line_chars=28,
                balance_lines=True,
                next_component_position="end_of_first_line",
            ),
            ComponentConfig("price", "soft_return", omit_sep_when_empty=False),
            ComponentConfig(
                "medium",
                "soft_return",
                omit_sep_when_empty=False,
                max_line_chars=52,
                balance_lines=True,
            ),
            ComponentConfig("artist", "soft_return", omit_sep_when_empty=False),
            ComponentConfig("edition", "none"),
            ComponentConfig("artwork", "tab", enabled=False),
        ],
    )


# ---------------------------------------------------------------------------
# Round-trip identity gate
# ---------------------------------------------------------------------------


def _roundtrip_check(sections, works, config):
    """Render -> parse -> assert each parsed entry equals the display strings
    computed straight from the resolved work, and counts/sections line up."""
    db = FakeSession(sections, works)
    text = render_import_as_tagged_text("imp1", db, config)
    parsed = parse_low_tags(text, config)

    # Flatten the resolved data and pair by catalogue number.
    collected = _collect_export_data("imp1", db)
    expected_by_cat = {}
    section_by_cat = {}
    for sec in collected:
        for w in sec["works"]:
            cat = str(w["number"])
            expected_by_cat[cat] = work_display_fields(w, config)
            section_by_cat[cat] = sec["section_name"]

    assert len(parsed) == len(expected_by_cat), "entry count mismatch"
    for entry in parsed:
        assert entry.cat_no in expected_by_cat, f"unexpected cat no {entry.cat_no}"
        assert entry.fields == expected_by_cat[entry.cat_no], (
            f"field mismatch for cat {entry.cat_no}: "
            f"{entry.fields} != {expected_by_cat[entry.cat_no]}"
        )
        assert entry.section_name == section_by_cat[entry.cat_no]


def test_roundtrip_default_config():
    sections = [_section("s1", "Gallery I", 1), _section("s2", "Gallery II", 2)]
    works = [
        _work(
            "s1", 1, 1,
            artist_name="Cornelia Parker", artist_honorifics="RA",
            title="Cold Dark Matter", price_numeric=12000,
            edition_total=7, edition_price_numeric=920, medium="mixed media",
        ),
        _work(
            "s1", 2, 2,
            artist_name="Anish Kapoor", title="Void", price_text="NFS",
            medium="pigment on fibreglass",
        ),
        _work(
            "s2", 1, 3,
            artist_name="David Hockney", title="Spring", edition_total=5,
            medium="iPad drawing",
        ),
    ]
    _roundtrip_check(sections, works, ExportConfig())


def test_roundtrip_2026_config_with_wrap_collision_and_interleave():
    config = _config_2026()
    sections = [_section("s1", "Central Hall", 1)]
    works = [
        # Long title forces a wrap; price is interleaved into the first line;
        # cat-no and title share the "Work Number/Name" style.
        _work(
            "s1", 1, 101,
            artist_name="Grayson Perry", artist_honorifics="RA",
            title="A Really Quite Long Painting Title That Must Wrap",
            price_numeric=1500,
            medium="Oil, acrylic and mixed media on reclaimed canvas board",
        ),
        _work(
            "s1", 2, 102,
            artist_name="Tracey Emin",
            title="Short One", price_numeric=8000,
            edition_total=3, edition_price_numeric=450, medium="neon",
        ),
    ]
    _roundtrip_check(sections, works, config)


# ---------------------------------------------------------------------------
# Targeted parser unit tests (hand-crafted inputs)
# ---------------------------------------------------------------------------


def test_collision_and_interleave_assignment():
    """First span of a shared style is the cat number; the rest is the title,
    even when a price span is interleaved between the title fragments."""
    config = ExportConfig(
        section_style="Sec",
        entry_style="Entry",
        cat_no_style="WNN",
        title_style="WNN",
        price_style="Price",
        components=[
            ComponentConfig("work_number", "tab"),
            ComponentConfig(
                "title", "tab", max_line_chars=10,
                next_component_position="end_of_first_line",
            ),
            ComponentConfig("price", "none"),
        ],
    )
    body = (
        "<CharStyle:WNN>42<CharStyle:>\t"
        "<CharStyle:WNN>Title part one <CharStyle:>"
        "<CharStyle:Price>£5<CharStyle:>"
        "<CharStyle:WNN>\ntitle part two<CharStyle:>"
    )
    doc = f"<ASCII-MAC>\r<ParaStyle:Sec>Room One\r<ParaStyle:Entry>{body}\r"
    parsed = parse_low_tags(doc, config)
    assert len(parsed) == 1
    e = parsed[0]
    assert e.cat_no == "42"
    assert e.section_name == "Room One"
    assert e.fields["work_number"] == "42"
    assert e.fields["title"] == "Title part one title part two"
    assert e.fields["price"] == "£5"


def test_allowlist_ignores_foreign_paragraphs():
    config = ExportConfig(section_style="Sec", entry_style="Entry")
    doc = (
        "<ASCII-MAC>\r"
        "<ParaStyle:Sec>Room\r"
        "<ParaStyle:Caption>a photo caption that must be ignored\r"
        "<ParaStyle:Spacer><cnxc:Column>\r"
        "<ParaStyle:Entry><CharStyle:CatNo>7<CharStyle:>\t"
        "<CharStyle:WorkTitle>Real Work<CharStyle:>\r"
    )
    parsed = parse_low_tags(doc, config)
    assert len(parsed) == 1
    assert parsed[0].cat_no == "7"
    assert parsed[0].fields["title"] == "Real Work"


def test_numeric_escape_is_decoded():
    config = ExportConfig(section_style="Sec", entry_style="Entry")
    doc = (
        "<ASCII-MAC>\r<ParaStyle:Sec>Room\r"
        "<ParaStyle:Entry><CharStyle:CatNo>9<CharStyle:>\t"
        "<CharStyle:WorkTitle>M<0x2019>Coul<CharStyle:>\r"
    )
    parsed = parse_low_tags(doc, config)
    assert parsed[0].fields["title"] == "M’Coul"
