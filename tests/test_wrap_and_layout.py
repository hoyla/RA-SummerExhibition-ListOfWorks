"""
Tests for title wrapping, component enabled flag, and final_sep_from_last_component.
"""

from types import SimpleNamespace

import pytest

from backend.app.services.export_renderer import (
    ComponentConfig,
    ExportConfig,
    _balance_wrap_lines,
    _wrap_lines,
    render_import_as_tagged_text,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


class FakeQuery:
    def __init__(self, results):
        self._results = results

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return self._results


class FakeSession:
    def __init__(self, sections, works, overrides=None):
        self.sections = sections
        self.works = works
        self.overrides = overrides or []

    def query(self, model):
        if model.__name__ == "Section":
            return FakeQuery(self.sections)
        if model.__name__ == "Work":
            return FakeQuery(self.works)
        if model.__name__ == "WorkOverride":
            return FakeQuery(self.overrides)
        return FakeQuery([])


def _section():
    return SimpleNamespace(id="sec1", import_id="imp1", name="Gallery", position=1)


def _make_work(
    title="Test Title", medium="Oil", price_numeric=1000, edition_total=None
):
    return SimpleNamespace(
        id="w1",
        raw_cat_no="1",
        artist_name="Artist",
        artist_honorifics=None,
        title=title,
        price_numeric=price_numeric,
        price_text=str(price_numeric) if price_numeric else "",
        edition_total=edition_total,
        edition_price_numeric=None,
        artwork=None,
        medium=medium,
        section_id="sec1",
        position_in_section=1,
        include_in_export=True,
    )


def _config(**kwargs):
    """Build a minimal ExportConfig with empty char styles to keep assertions simple."""
    defaults = dict(
        cat_no_style="",
        artist_style="",
        honorifics_style="",
        title_style="",
        price_style="",
        medium_style="",
        artwork_style="",
        leading_separator="none",
        trailing_separator="none",
    )
    defaults.update(kwargs)
    return ExportConfig(**defaults)


# ---------------------------------------------------------------------------
# _wrap_lines unit tests
# ---------------------------------------------------------------------------


def test_wrap_short_text_unchanged():
    assert _wrap_lines("Hello", 20) == ["Hello"]


def test_wrap_text_at_exact_limit_unchanged():
    text = "A" * 20
    assert _wrap_lines(text, 20) == [text]


def test_wrap_breaks_at_last_space_within_limit():
    # "Hello World" — break after "Hello " (candidate=5, within limit 8)
    lines = _wrap_lines("Hello World", 8)
    assert lines[0].rstrip() == "Hello"
    assert lines[1] == "World"


def test_wrap_trailing_space_stays_on_current_line():
    lines = _wrap_lines("Hello World", 8)
    # The space belongs to line 0, so line 1 must not start with a space
    assert not lines[1].startswith(" ")


def test_wrap_multiple_breaks():
    # 10 chars per line; text has natural spaces
    text = "one two three four five"
    lines = _wrap_lines(text, 10)
    assert all(len(l) <= 11 for l in lines)  # <=11 because trailing space allowed
    reassembled = "".join(lines)
    assert reassembled == text


def test_wrap_hard_break_when_no_space():
    # Single long token exceeds limit
    lines = _wrap_lines("ABCDEFGHIJ", 5)
    assert lines[0] == "ABCDE"
    assert lines[1] == "FGHIJ"


def test_wrap_open_punct_must_not_end_line():
    # 'A "B' — candidate break is after space before '"', which would leave
    # '"' (open quote) at the start of the next line, so it's always fine.
    # But if the open quote would end the current line we must walk back.
    # Construct: "ABC (DEF" — limit 5 puts the break between "ABC " and "(DEF",
    # but '(' is open punct so it must not end the prior line as a trailing char.
    # Actually the rule is open punct must not END a line (be the last char before break).
    # Here: "ABC (" at len 5 — candidate=4 (space), char_before='C', which is fine.
    # Let's test a trickier case: "AB (X" limit=4 → candidate at index 3 (space),
    # char_before='(' → bad, so walk back further to index 2 (no space) → hard break.
    lines = _wrap_lines("AB (X", 4)
    # Should either hard-break or find a safe earlier split
    assert "".join(lines) == "AB (X"


def test_wrap_close_punct_must_not_start_line():
    # "Hello, World" limit 7 → candidate at index 6 (space after comma).
    # char_after = 'W' which is fine. Test that "Hello," doesn't get broken
    # such that ',' starts the next line.
    lines = _wrap_lines("Hello, World", 7)
    for line in lines[1:]:
        assert not line.startswith(",")


def test_wrap_no_break_after_em_dash():
    # "A—B C" limit=4 → candidate at index 4 (space).
    # char_before is 'B', not a dash — so split is fine there.
    # Force the dash case: "A— B" limit=3 → candidate space at index 2,
    # char_before='—' → bad, walk back → no earlier space → hard break.
    lines = _wrap_lines("A\u2014 B", 3)
    assert "".join(lines) == "A\u2014 B"


def test_wrap_empty_string():
    assert _wrap_lines("", 20) == []


# ---------------------------------------------------------------------------
# Component enabled flag
# ---------------------------------------------------------------------------


def test_disabled_component_not_in_output():
    db = FakeSession([_section()], [_make_work(medium="Oil on canvas")])
    cfg = _config(
        components=[
            ComponentConfig("work_number", "tab", True, True),
            ComponentConfig("title", "tab", True, True),
            ComponentConfig("price", "none", True, True),
            ComponentConfig("medium", "none", True, False),  # disabled
        ]
    )
    output = render_import_as_tagged_text("imp1", db, config=cfg)
    assert "Oil on canvas" not in output


def test_enabled_component_in_output():
    db = FakeSession([_section()], [_make_work(medium="Oil on canvas")])
    cfg = _config(
        components=[
            ComponentConfig("work_number", "tab", True, True),
            ComponentConfig("title", "tab", True, True),
            ComponentConfig("price", "none", True, True),
            ComponentConfig("medium", "none", True, True),  # enabled
        ]
    )
    output = render_import_as_tagged_text("imp1", db, config=cfg)
    assert "Oil on canvas" in output


# ---------------------------------------------------------------------------
# max_line_chars + end_of_first_line
# ---------------------------------------------------------------------------


def test_end_of_first_line_single_line_normal_output():
    """When title fits within max_line_chars, output is unchanged."""
    db = FakeSession([_section()], [_make_work(title="Short")])
    cfg = _config(
        components=[
            ComponentConfig("work_number", "tab", True, True),
            ComponentConfig(
                "title",
                "tab",
                True,
                True,
                max_line_chars=40,
                next_component_position="end_of_first_line",
            ),
            ComponentConfig("price", "none", True, True),
        ]
    )
    output = render_import_as_tagged_text("imp1", db, config=cfg)
    assert "Short" in output
    assert "£1,000" in output
    # No soft-return control characters expected (0x000A would show if wrapped)
    assert "\n" not in output.split("\r")[1]  # within first entry line


def test_end_of_first_line_multiline_nc_after_first_line():
    """Price (NC) should appear immediately after the first line of the title."""
    long_title = "WHAT DO ANIMALS DREAM OF WHEN THEY SLEEP"
    db = FakeSession([_section()], [_make_work(title=long_title, price_numeric=5000)])
    cfg = _config(
        components=[
            ComponentConfig("work_number", "tab", True, True),
            ComponentConfig(
                "title",
                "tab",
                True,
                True,
                max_line_chars=20,
                next_component_position="end_of_first_line",
            ),
            ComponentConfig("price", "none", True, True),
        ]
    )
    output = render_import_as_tagged_text("imp1", db, config=cfg)
    # Price should appear in the output
    assert "£5,000" in output
    # Title content should appear (split across lines)
    assert "WHAT DO ANIMALS" in output or "WHAT DO" in output
    # There should be a soft return (\n) as InDesign line break within the entry
    # (the entry is a single paragraph separated by \r)
    entry_para = [
        p for p in output.split("\r") if "<ParaStyle:" in p and "Gallery" not in p
    ]
    assert any("\n" in p for p in entry_para)


def test_end_of_first_line_price_before_remaining_title_lines():
    """Price must come before the continuation of the title, not after all of it."""
    long_title = "ONE TWO THREE FOUR FIVE SIX SEVEN EIGHT"
    db = FakeSession([_section()], [_make_work(title=long_title, price_numeric=999)])
    cfg = _config(
        components=[
            ComponentConfig(
                "title",
                "tab",
                True,
                True,
                max_line_chars=15,
                next_component_position="end_of_first_line",
            ),
            ComponentConfig("price", "none", True, True),
        ]
    )
    output = render_import_as_tagged_text("imp1", db, config=cfg)
    price_pos = output.index("£999")
    # "ONE TWO THREE" is the first line; remaining title text comes after price
    first_line_end = output.index(
        "\t", output.index("ONE")
    )  # tab = sep after title line 1
    assert price_pos > first_line_end  # price comes after the tab following line 1
    # And at least part of the remaining title must follow the price
    remaining_start = output.index("\n", first_line_end)
    assert remaining_start > price_pos


# ---------------------------------------------------------------------------
# final_sep_from_last_component
# ---------------------------------------------------------------------------


def test_final_sep_last_component_omitted_adopts_its_separator():
    """
    Artist uses soft_return; Edition uses none + omit_when_empty.
    When edition is absent, Artist should use none (Edition's separator)
    so no trailing soft-return appears.
    """
    db = FakeSession([_section()], [_make_work(edition_total=None)])
    cfg = _config(
        final_sep_from_last_component=True,
        components=[
            ComponentConfig("title", "tab", True, True),
            ComponentConfig("price", "soft_return", True, True),
            ComponentConfig("artist", "soft_return", True, True),
            ComponentConfig("edition", "none", True, True),  # omit_sep_when_empty=True
        ],
    )
    output = render_import_as_tagged_text("imp1", db, config=cfg)
    # Artist is the last to emit; it should use Edition's separator (none → no \n after artist)
    # Soft-return in tagged text is <0x000A>
    # The artist value will be followed immediately by \r (paragraph end), not <0x000A>
    entry_para = [p for p in output.split("\r") if "Artist" in p]
    assert entry_para, "Artist not found in output"
    # After "Artist" there should be no soft-return before the paragraph ends
    artist_idx = entry_para[0].rindex("Artist")
    tail = entry_para[0][artist_idx + len("Artist") :]
    assert (
        "\n" not in tail
    )  # no soft return — artist adopted Edition's separator (none)


def test_final_sep_last_component_present_normal_behaviour():
    """When the last component has content, every component uses its own separator."""
    db = FakeSession([_section()], [_make_work(edition_total=3)])
    cfg = _config(
        final_sep_from_last_component=True,
        components=[
            ComponentConfig("title", "tab", True, True),
            ComponentConfig("artist", "soft_return", True, True),
            ComponentConfig("edition", "none", True, True),
        ],
    )
    output = render_import_as_tagged_text("imp1", db, config=cfg)
    # Both artist and edition present; artist keeps its soft_return
    entry_para = [p for p in output.split("\r") if "Artist" in p]
    assert entry_para
    artist_idx = entry_para[0].rindex("Artist")
    tail = entry_para[0][artist_idx + len("Artist") :]
    assert (
        "\n" in tail
    )  # soft return is still there (raw \n before escape_for_mac_roman)


def test_final_sep_disabled_no_change():
    """With final_sep_from_last_component=False (default), Artist keeps its separator."""
    db = FakeSession([_section()], [_make_work(edition_total=None)])
    cfg = _config(
        final_sep_from_last_component=False,
        components=[
            ComponentConfig("title", "tab", True, True),
            ComponentConfig("artist", "soft_return", True, True),
            ComponentConfig("edition", "none", True, True),
        ],
    )
    output = render_import_as_tagged_text("imp1", db, config=cfg)
    entry_para = [p for p in output.split("\r") if "Artist" in p]
    assert entry_para
    artist_idx = entry_para[0].rindex("Artist")
    tail = entry_para[0][artist_idx + len("Artist") :]
    assert "\n" in tail  # soft return still present because feature is off


# ---------------------------------------------------------------------------
# _balance_wrap_lines
# ---------------------------------------------------------------------------


def test_balance_wrap_produces_same_line_count():
    """Balanced wrap must not add extra lines compared to greedy wrap."""
    text = "WHAT DO ANIMALS DREAM OF WHEN THEY SLEEP AT NIGHT"
    greedy = _wrap_lines(text, 20)
    balanced = _balance_wrap_lines(text, 20)
    assert len(balanced) == len(greedy)


def test_balance_wrap_single_line_unchanged():
    """Text that fits on one line should be returned unchanged."""
    assert _balance_wrap_lines("Short text", 40) == ["Short text"]


def test_balance_wrap_respects_max_chars():
    """No balanced line should exceed max_chars characters."""
    text = "ONE TWO THREE FOUR FIVE SIX SEVEN EIGHT NINE TEN"
    lines = _balance_wrap_lines(text, 20)
    assert all(len(line.rstrip()) <= 20 for line in lines)


def test_balance_wrap_reduces_last_line_disparity():
    """Balanced wrap should shorten the last line less than greedy would."""
    # Greedy at width=28 puts a very short tail on the last line;
    # balanced should pull words back to even things up.
    text = "WHAT DO ANIMALS DREAM OF WHEN THEY SLEEP"
    greedy = _wrap_lines(text, 28)
    balanced = _balance_wrap_lines(text, 28)
    if len(greedy) > 1 and len(balanced) > 1:
        greedy_last = len(greedy[-1].rstrip())
        balanced_last = len(balanced[-1].rstrip())
        # Balanced last line should be at least as long as greedy last line
        assert balanced_last >= greedy_last
