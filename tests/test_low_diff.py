"""Diff-engine tests for the LOW → LPG reconciliation feature.

Renders a base import, then simulates downstream InDesign edits by manipulating
the exported tag string the way a staffer would (text edits, renumbering, moving
an entry to another room), re-parses, and asserts the diff classifies each
disparity correctly — including suppressing cosmetic noise.
"""

from types import SimpleNamespace

from backend.app.services.export_renderer import (
    ExportConfig,
    _collect_export_data,
    render_import_as_tagged_text,
)
from backend.app.services.low_diff import LowDiffConfig, diff_low
from backend.app.services.low_tag_parser import ParsedEntry, parse_low_tags

# --- minimal in-memory session -------------------------------------------------


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
    def __init__(self, sections, works):
        self.sections, self.works = sections, works

    def query(self, model):
        return {
            "Section": FakeQuery(self.sections),
            "Work": FakeQuery(self.works),
            "WorkOverride": FakeQuery([]),
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


def _base_import():
    """Two rooms; Gallery II has three works so a single mover doesn't drag the
    whole room's alignment with it."""
    config = ExportConfig()
    sections = [_section("s1", "Gallery I", 1), _section("s2", "Gallery II", 2)]
    works = [
        _work(
            "s1",
            1,
            101,
            artist_name="Cornelia Parker",
            artist_honorifics="RA",
            title="Cold Dark Matter",
            price_numeric=12000,
            medium="mixed media",
        ),
        _work(
            "s1",
            2,
            102,
            artist_name="Anish Kapoor",
            title="Void",
            price_text="NFS",
            medium="pigment",
        ),
        _work(
            "s2",
            1,
            103,
            artist_name="David Hockney",
            title="Spring",
            price_numeric=9000,
            medium="iPad drawing",
        ),
        _work(
            "s2",
            2,
            104,
            artist_name="Rachel Whiteread",
            title="Artist's Study",
            price_numeric=5000,
            medium="resin",
        ),
        _work(
            "s2",
            3,
            105,
            artist_name="Frank Bowling",
            title="Map",
            price_numeric=7000,
            medium="acrylic on canvas",
        ),
    ]
    db = FakeSession(sections, works)
    text = render_import_as_tagged_text("imp1", db, config)
    collected = _collect_export_data("imp1", db)
    return config, text, collected


def _catspan(config, cat_no):
    return f"<CharStyle:{config.cat_no_style}>{cat_no}<CharStyle:>"


def _move_entry(text, cat_no, target_section, config):
    """Relocate the entry paragraph for cat_no to sit under another section
    heading (as a designer dragging a frame would end up doing in the tags)."""
    paras = text.split("\r")
    span = _catspan(config, cat_no)
    ei = next(
        i
        for i, p in enumerate(paras)
        if p.startswith(f"<ParaStyle:{config.entry_style}>") and span in p
    )
    entry = paras.pop(ei)
    ti = next(
        i
        for i, p in enumerate(paras)
        if p.startswith(f"<ParaStyle:{config.section_style}>{target_section}")
    )
    paras.insert(ti + 1, entry)
    return "\r".join(paras)


def _diff_modified(config, modified_text, collected):
    return diff_low(parse_low_tags(modified_text, config), collected, config)


def _kinds(result):
    return [f.kind for f in result.findings]


# --- tests ---------------------------------------------------------------------


def test_baseline_no_findings():
    config, text, collected = _base_import()
    result = _diff_modified(config, text, collected)
    assert result.findings == []
    assert result.counts["matched"] == 5
    assert result.counts["suppressed_cosmetic"] == 0


def test_text_edit_detected():
    config, text, collected = _base_import()
    modified = text.replace("Cold Dark Matter", "Cold Dark Matter Revisited")
    result = _diff_modified(config, modified, collected)
    changes = [f for f in result.findings if f.kind == "field_change"]
    assert len(changes) == 1
    f = changes[0]
    assert f.cat_no == "101" and f.field == "title"
    assert f.low_value == "Cold Dark Matter Revisited"
    assert f.fix_channel == "override"
    assert f.severity == "medium"


def test_renumber_shows_as_add_and_remove():
    config, text, collected = _base_import()
    modified = text.replace(_catspan(config, 102), _catspan(config, 120))
    result = _diff_modified(config, modified, collected)
    added = [f for f in result.findings if f.kind == "entry_added"]
    removed = [f for f in result.findings if f.kind == "entry_removed"]
    assert [f.cat_no for f in added] == ["120"]
    assert [f.cat_no for f in removed] == ["102"]
    # Structural → routed to the spreadsheet re-import channel, high severity.
    assert added[0].fix_channel == "spreadsheet"
    assert added[0].severity == "high"


def test_room_move_detected():
    config, text, collected = _base_import()
    modified = _move_entry(text, 103, "Gallery I", config)
    result = _diff_modified(config, modified, collected)
    moves = [f for f in result.findings if f.kind == "room_move"]
    assert len(moves) == 1
    assert moves[0].cat_no == "103"
    assert moves[0].db_value == "Gallery II" and moves[0].low_value == "Gallery I"
    assert moves[0].severity == "high"
    assert moves[0].fix_channel == "spreadsheet"


def test_section_rename_not_seen_as_moves():
    config, text, collected = _base_import()
    # Designer embellishes the heading for print; works stay put.
    modified = text.replace(
        "<ParaStyle:SectionTitle>Gallery I\r",
        "<ParaStyle:SectionTitle>Gallery I — supported by Acme\r",
    )
    result = _diff_modified(config, modified, collected)
    assert not [f for f in result.findings if f.kind == "room_move"]
    renames = [f for f in result.findings if f.kind == "section_rename"]
    assert len(renames) == 1
    assert renames[0].severity == "info"
    assert result.counts["matched"] == 5


def test_cosmetic_changes_suppressed():
    config, text, collected = _base_import()
    # Smart apostrophe (InDesign auto-convert) + an injected double space.
    modified = text.replace("Artist's Study", "Artist’s  Study")
    result = _diff_modified(config, modified, collected)
    assert [f for f in result.findings if f.cat_no == "104"] == []
    assert result.counts["suppressed_cosmetic"] >= 1
    # The suppressed difference is retained (viewable) with severity "cosmetic".
    cos = [f for f in result.cosmetic if f.cat_no == "104" and f.field == "title"]
    assert len(cos) == 1 and cos[0].severity == "cosmetic"
    assert cos[0].low_value == "Artist’s  Study"  # raw value kept, for drill-in


def test_cosmetic_surfaces_when_suppression_disabled():
    config, text, collected = _base_import()
    modified = text.replace("Artist's Study", "Artist’s Study")
    diff_cfg = LowDiffConfig(fold_typographic=False, suppress_cosmetic=False)
    result = diff_low(parse_low_tags(modified, config), collected, config, diff_cfg)
    changes = [f for f in result.findings if f.cat_no == "104"]
    assert len(changes) == 1 and changes[0].field == "title"


def test_tiering_is_configurable():
    config, text, collected = _base_import()
    modified = text.replace("£12,000", "£15,000")  # price change on cat 101
    diff_cfg = LowDiffConfig.from_dict({"severity": {"field_change": {"price": "high"}}})
    result = diff_low(parse_low_tags(modified, config), collected, config, diff_cfg)
    price_changes = [f for f in result.findings if f.field == "price"]
    assert len(price_changes) == 1
    assert price_changes[0].severity == "high"  # tuned up from the medium default


def test_manual_newline_in_field_is_not_a_finding():
    """A manual line break in a source field (e.g. a multi-line medium) is kept
    in the DB but deleted by the parser when it round-trips through InDesign's
    soft returns. That must read as cosmetic, not a real change. (Found on the
    real 2025 catalogue.)"""
    collected = [
        {
            "section_name": "Gallery I",
            "position": 1,
            "works": [
                {
                    "number": "1",
                    "artist": "A",
                    "honorifics": None,
                    "title": "T",
                    "price_numeric": 100,
                    "price_text": "",
                    "edition_total": None,
                    "edition_price_numeric": None,
                    "artwork": None,
                    "medium": "resin\nand steel",
                }
            ],
        }
    ]
    parsed = [
        ParsedEntry(
            cat_no="1",
            section_name="Gallery I",
            paragraph_index=0,
            fields={
                "work_number": "1",
                "artist": "A",
                "title": "T",
                "price": "£100",
                "medium": "resinand steel",
            },
        )
    ]
    result = diff_low(parsed, collected, ExportConfig())
    assert [f for f in result.findings if f.field == "medium"] == []
    assert result.counts["suppressed_cosmetic"] >= 1


def test_combined_canonical_mutations():
    """The showcase: a text edit, a renumber, and a room move in one file."""
    config, text, collected = _base_import()
    modified = text.replace("Cold Dark Matter", "Cold Dark Matter Revisited")
    modified = modified.replace(_catspan(config, 102), _catspan(config, 120))
    modified = _move_entry(modified, 103, "Gallery I", config)
    result = _diff_modified(config, modified, collected)

    kinds = _kinds(result)
    assert kinds.count("field_change") == 1
    assert kinds.count("entry_added") == 1
    assert kinds.count("entry_removed") == 1
    assert kinds.count("room_move") == 1

    assert result.counts["matched"] == 4  # 101, 103, 104, 105 (102 renumbered)
    assert result.counts["low_only"] == 1  # 120
    assert result.counts["db_only"] == 1  # 102
    # Every finding is routed and tiered.
    assert all(f.fix_channel in ("override", "spreadsheet") for f in result.findings)
    assert all(f.severity in ("high", "medium", "info") for f in result.findings)
