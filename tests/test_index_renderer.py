"""Tests for the Artists' Index renderer."""

import pytest

from backend.app.services.index_renderer import (
    ArtistExportEntry,
    IndexExportConfig,
    render_index_tagged_text,
    _render_name_part,
    _render_quals,
    _render_courtesy,
    _render_cat_nos,
    _cstyle,
    _letter_key,
    _section_sep,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entry(
    last_name=None,
    first_name=None,
    title=None,
    quals=None,
    company=None,
    is_ra=False,
    is_company=False,
    courtesy=None,
    cat_nos=None,
    sort_key="",
    artist2_first_name=None,
    artist2_last_name=None,
    artist2_quals=None,
    artist3_first_name=None,
    artist3_last_name=None,
    artist3_quals=None,
    artist1_ra_styled=None,
    artist2_ra_styled=False,
    artist3_ra_styled=False,
):
    # Default artist1_ra_styled to is_ra for backwards-compat in tests
    if artist1_ra_styled is None:
        artist1_ra_styled = is_ra
    return ArtistExportEntry(
        title=title,
        first_name=first_name,
        last_name=last_name,
        quals=quals,
        company=company,
        is_ra_member=is_ra,
        is_company=is_company,
        sort_key=sort_key,
        courtesy=courtesy,
        cat_nos=cat_nos or [],
        artist2_first_name=artist2_first_name,
        artist2_last_name=artist2_last_name,
        artist2_quals=artist2_quals,
        artist3_first_name=artist3_first_name,
        artist3_last_name=artist3_last_name,
        artist3_quals=artist3_quals,
        artist1_ra_styled=artist1_ra_styled,
        artist2_ra_styled=artist2_ra_styled,
        artist3_ra_styled=artist3_ra_styled,
    )


CFG = IndexExportConfig()


# ---------------------------------------------------------------------------
# Unit tests — building blocks
# ---------------------------------------------------------------------------


class TestCstyle:
    def test_basic(self):
        assert _cstyle("Bold", "hello") == "<cstyle:Bold>hello<cstyle:>"

    def test_empty_style(self):
        assert _cstyle("", "hello") == "hello"


class TestRenderCatNos:
    def test_single(self):
        result = _render_cat_nos([714], CFG)
        assert result == "<cstyle:Index works numbers>714<cstyle:>"

    def test_multiple(self):
        result = _render_cat_nos([101, 205, 318], CFG)
        assert result == (
            "<cstyle:Index works numbers>101<cstyle:>"
            ", <cstyle:Index works numbers>205<cstyle:>"
            ", <cstyle:Index works numbers>318<cstyle:>"
        )

    def test_separator_style(self):
        cfg = IndexExportConfig(cat_no_separator_style="Sep Style")
        result = _render_cat_nos([10, 20], cfg)
        assert result == (
            "<cstyle:Index works numbers>10<cstyle:>"
            "<cstyle:Sep Style>,<cstyle:>"
            " <cstyle:Index works numbers>20<cstyle:>"
        )

    def test_semicolon_separator(self):
        cfg = IndexExportConfig(cat_no_separator=";")
        result = _render_cat_nos([10, 20], cfg)
        assert result == (
            "<cstyle:Index works numbers>10<cstyle:>"
            "; <cstyle:Index works numbers>20<cstyle:>"
        )

    def test_empty(self):
        assert _render_cat_nos([], CFG) == ""


class TestRenderQuals:
    def test_ra_member(self):
        result = _render_quals("CBE RA", True, CFG)
        assert result == "<cstyle:RA Caps>cbe ra<cstyle:>, "

    def test_non_ra(self):
        result = _render_quals("OBE", False, CFG)
        assert result == "<cstyle:Small caps>obe<cstyle:>, "

    def test_no_quals(self):
        assert _render_quals(None, False, CFG) == ""

    def test_no_lowercase(self):
        cfg = IndexExportConfig(quals_lowercase=False)
        result = _render_quals("CBE RA", True, cfg)
        assert result == "<cstyle:RA Caps>CBE RA<cstyle:>, "


class TestRenderNamePart:
    def test_simple(self):
        e = _entry(last_name="Adams", first_name="Roger")
        assert _render_name_part(e, CFG) == "Adams, Roger, "

    def test_ra_member(self):
        e = _entry(last_name="Parker", first_name="Cornelia", is_ra=True)
        result = _render_name_part(e, CFG)
        assert result == "<cstyle:RA Member Cap Surname>Parker<cstyle:>, Cornelia, "

    def test_with_title(self):
        e = _entry(last_name="Adjaye", first_name="David", title="Sir", is_ra=True)
        result = _render_name_part(e, CFG)
        assert result == "<cstyle:RA Member Cap Surname>Adjaye<cstyle:>, Sir David, "

    def test_single_name_ra(self):
        e = _entry(first_name="Assemble", is_ra=True)
        result = _render_name_part(e, CFG)
        assert result == "<cstyle:RA Member Cap Surname>Assemble<cstyle:>, "

    def test_company(self):
        e = _entry(last_name="AKT II", is_company=True)
        result = _render_name_part(e, CFG)
        assert result == "AKT II, "

    def test_has_quals_strips_comma_after_first_name(self):
        """When quals follow, trailing separator after first name is space not comma."""
        e = _entry(last_name="Parker", first_name="Cornelia", is_ra=True)
        result = _render_name_part(e, CFG, has_quals=True)
        assert result == "<cstyle:RA Member Cap Surname>Parker<cstyle:>, Cornelia "

    def test_has_quals_single_name(self):
        """Single-name entry with quals: surname separator is space not comma."""
        e = _entry(first_name="Assemble", is_ra=True)
        result = _render_name_part(e, CFG, has_quals=True)
        assert result == "<cstyle:RA Member Cap Surname>Assemble<cstyle:> "

    def test_expert_numbers_enabled(self):
        cfg = IndexExportConfig(expert_numbers_enabled=True)
        e = _entry(last_name="8014")
        result = _render_name_part(e, cfg)
        assert result == "<cstyle:Expert numbers>8014<cstyle:>, "

    def test_expert_numbers_partial(self):
        """Name with leading digits like '51 Architecture'."""
        cfg = IndexExportConfig(expert_numbers_enabled=True)
        e = _entry(last_name="51 Architecture")
        result = _render_name_part(e, cfg)
        assert result == "<cstyle:Expert numbers>51<cstyle:> Architecture, "

    def test_expert_numbers_disabled(self):
        cfg = IndexExportConfig(expert_numbers_enabled=False)
        e = _entry(last_name="8014")
        result = _render_name_part(e, cfg)
        assert result == "8014, "

    def test_the_late(self):
        e = _entry(
            last_name="Ackroyd", first_name="Norman", title="The late Prof.", is_ra=True
        )
        result = _render_name_part(e, CFG)
        assert (
            result
            == "<cstyle:RA Member Cap Surname>Ackroyd<cstyle:>, The late Prof. Norman, "
        )


class TestRenderCourtesy:
    def test_courtesy(self):
        assert (
            _render_courtesy("Courtesy of Flowers Gallery", None)
            == "Courtesy of Flowers Gallery, "
        )

    def test_company(self):
        assert _render_courtesy(None, "Adjaye Associates") == "Adjaye Associates, "

    def test_neither(self):
        assert _render_courtesy(None, None) == ""


# ---------------------------------------------------------------------------
# Integration tests — full render
# ---------------------------------------------------------------------------


class TestFullRender:
    def test_simple_entry(self):
        entries = [_entry(last_name="Adams", first_name="Roger", cat_nos=[1266, 1276])]
        result = render_index_tagged_text(entries, CFG)
        expected_line = (
            "<pstyle:Index Text>Adams, Roger, "
            "<cstyle:Index works numbers>1266<cstyle:>"
            ", <cstyle:Index works numbers>1276<cstyle:>"
        )
        assert expected_line in result

    def test_ra_member_with_courtesy(self):
        entries = [
            _entry(
                last_name="Armfield",
                first_name="Diana",
                quals="RA",
                is_ra=True,
                courtesy="courtesy of Browse and Draby",
                cat_nos=[597, 948, 1428, 1429, 1430, 1431],
            )
        ]
        result = render_index_tagged_text(entries, CFG)
        assert "<cstyle:RA Member Cap Surname>Armfield<cstyle:>, " in result
        assert "<cstyle:RA Caps>ra<cstyle:>, " in result
        assert "courtesy of Browse and Draby, " in result
        assert "<cstyle:Index works numbers>597<cstyle:>" in result

    def test_ra_member_with_company(self):
        entries = [
            _entry(
                last_name="Adjaye",
                first_name="David",
                title="Sir",
                quals="OM OBE RA",
                is_ra=True,
                company="Adjaye Associates",
                cat_nos=[124],
            )
        ]
        result = render_index_tagged_text(entries, CFG)
        assert "<cstyle:RA Member Cap Surname>Adjaye<cstyle:>, Sir David " in result
        assert "<cstyle:RA Caps>om obe ra<cstyle:>, " in result
        assert "Adjaye Associates, " in result

    def test_company_entry(self):
        entries = [
            _entry(
                last_name="AKT II",
                is_company=True,
                company="AKT II",
                cat_nos=[787, 788],
            )
        ]
        result = render_index_tagged_text(entries, CFG)
        assert "<pstyle:Index Text>AKT II, " in result

    def test_single_name_ra(self):
        entries = [
            _entry(
                first_name="Assemble",
                quals="RA",
                is_ra=True,
                cat_nos=[607, 705, 721, 779, 780, 1589],
            )
        ]
        result = render_index_tagged_text(entries, CFG)
        assert "<cstyle:RA Member Cap Surname>Assemble<cstyle:> " in result
        assert "<cstyle:RA Caps>ra<cstyle:>, " in result

    def test_header(self):
        entries = [_entry(last_name="Test", first_name="A", cat_nos=[1])]
        result = render_index_tagged_text(entries, CFG)
        assert result.startswith("<ASCII-MAC>")

    def test_line_separator(self):
        """Lines separated by \\r (Mac line endings for InDesign)."""
        entries = [
            _entry(last_name="Adams", first_name="Roger", cat_nos=[1]),
            _entry(last_name="Baker", first_name="Sue", cat_nos=[2]),
        ]
        result = render_index_tagged_text(entries, CFG)
        lines = result.split("\r")
        assert len(lines) == 3  # header + 2 entries

    def test_multi_entry_sorted_output(self):
        """Entries should appear in the order provided (pre-sorted)."""
        entries = [
            _entry(
                last_name="Abramović",
                first_name="Marina",
                quals="HON RA",
                is_ra=True,
                courtesy="courtesy of Lisson Gallery",
                cat_nos=[1170],
                sort_key="abramovic marina",
            ),
            _entry(
                last_name="Adams",
                first_name="Roger",
                cat_nos=[399],
                sort_key="adams roger",
            ),
            _entry(
                last_name="Parker",
                first_name="Cornelia",
                quals="CBE RA",
                is_ra=True,
                courtesy="courtesy of Frith Street Gallery",
                cat_nos=[1216, 1238, 1452],
                sort_key="parker cornelia",
            ),
        ]
        result = render_index_tagged_text(entries, CFG)
        lines = result.split("\r")
        # Line 0 = header, 1 = Abramovic, 2 = Adams, 3 = separator (A→P), 4 = Parker
        assert "Abramovi" in lines[1]
        assert "Adams" in lines[2]
        assert "Parker" in lines[4]

    def test_non_ra_courtesy_entry(self):
        """Non-RA artist with courtesy line."""
        entries = [
            _entry(
                last_name="Armstrong-Jones",
                first_name="Sarah",
                courtesy="courtesy of The Redfern Gallery",
                cat_nos=[1083],
            )
        ]
        result = render_index_tagged_text(entries, CFG)
        line = result.split("\r")[1]
        assert "Armstrong-Jones, Sarah, " in line
        assert "courtesy of The Redfern Gallery, " in line
        # Should NOT have RA styling
        assert "RA Member Cap Surname" not in line
        assert "RA Caps" not in line

    def test_matches_edited_output_ackroyd(self):
        """Compare against the known-good edited output for Ackroyd."""
        entries = [
            _entry(
                last_name="Ackroyd",
                first_name="Norman",
                title="The late Prof.",
                quals="CBE RA",
                is_ra=True,
                cat_nos=[57, 58, 59, 61, 62, 63],
            )
        ]
        result = render_index_tagged_text(entries, CFG)
        line = result.split("\r")[1]
        expected = (
            "<pstyle:Index Text>"
            "<cstyle:RA Member Cap Surname>Ackroyd<cstyle:>, "
            "The late Prof. Norman "
            "<cstyle:RA Caps>cbe ra<cstyle:>, "
            "<cstyle:Index works numbers>57<cstyle:>"
            ", <cstyle:Index works numbers>58<cstyle:>"
            ", <cstyle:Index works numbers>59<cstyle:>"
            ", <cstyle:Index works numbers>61<cstyle:>"
            ", <cstyle:Index works numbers>62<cstyle:>"
            ", <cstyle:Index works numbers>63<cstyle:>"
        )
        assert line == expected

    def test_matches_edited_output_adjaye(self):
        """Compare against the known-good edited output for Adjaye."""
        entries = [
            _entry(
                last_name="Adjaye",
                first_name="David",
                title="Sir",
                quals="OM OBE RA",
                is_ra=True,
                company="Adjaye Associates",
                cat_nos=[124],
            )
        ]
        result = render_index_tagged_text(entries, CFG)
        line = result.split("\r")[1]
        expected = (
            "<pstyle:Index Text>"
            "<cstyle:RA Member Cap Surname>Adjaye<cstyle:>, "
            "Sir David "
            "<cstyle:RA Caps>om obe ra<cstyle:>, "
            "Adjaye Associates, "
            "<cstyle:Index works numbers>124<cstyle:>"
        )
        assert line == expected


# ---------------------------------------------------------------------------
# Full render — additional artists with RA styling
# ---------------------------------------------------------------------------


class TestAdditionalArtistRaStyling:
    def test_artist2_ra_styling(self):
        """Artist 2 RA quals should be styled with RA Caps."""
        entries = [
            _entry(
                last_name="Sauerbruch",
                first_name="Matthias",
                artist2_first_name="Peter",
                artist2_last_name="St John",
                artist2_quals="ra",
                artist2_ra_styled=True,
                cat_nos=[42],
            )
        ]
        result = render_index_tagged_text(entries, CFG)
        line = result.split("\r")[1]
        expected = (
            "<pstyle:Index Text>"
            "Sauerbruch, Matthias, "
            "and Peter "
            "<cstyle:RA Member Cap Surname>St John<cstyle:> "
            "<cstyle:RA Caps>ra<cstyle:>, "
            "<cstyle:Index works numbers>42<cstyle:>"
        )
        assert line == expected

    def test_artist2_no_ra_styling(self):
        """Artist 2 without RA styling should render plain."""
        entries = [
            _entry(
                last_name="Sauerbruch",
                first_name="Matthias",
                artist2_first_name="Peter",
                artist2_last_name="St John",
                cat_nos=[42],
            )
        ]
        result = render_index_tagged_text(entries, CFG)
        line = result.split("\r")[1]
        expected = (
            "<pstyle:Index Text>"
            "Sauerbruch, Matthias, "
            "and Peter St John, "
            "<cstyle:Index works numbers>42<cstyle:>"
        )
        assert line == expected


# ---------------------------------------------------------------------------
# Section separator
# ---------------------------------------------------------------------------


class TestSectionSep:
    def test_paragraph(self):
        assert _section_sep("paragraph") == "\r"

    def test_column_break(self):
        assert _section_sep("column_break") == "<cnxc:Column>\r"

    def test_frame_break(self):
        assert _section_sep("frame_break") == "<cnxc:Frame>\r"

    def test_page_break(self):
        assert _section_sep("page_break") == "<cnxc:Page>\r"

    def test_none(self):
        assert _section_sep("none") == ""

    def test_with_style(self):
        assert _section_sep("paragraph", "Spacer") == "<pstyle:Spacer>\r"
        assert (
            _section_sep("column_break", "Spacer") == "<pstyle:Spacer><cnxc:Column>\r"
        )


class TestLetterKey:
    def test_alpha(self):
        assert _letter_key(_entry(sort_key="adams")) == "A"

    def test_digit(self):
        assert _letter_key(_entry(sort_key="8014")) == "#"

    def test_uppercase(self):
        assert _letter_key(_entry(sort_key="Zaha")) == "Z"


class TestLetterGroupRendering:
    def test_separator_between_letter_groups(self):
        entries = [
            _entry(last_name="Adams", sort_key="adams", cat_nos=[1]),
            _entry(last_name="Baker", sort_key="baker", cat_nos=[2]),
        ]
        result = render_index_tagged_text(entries, CFG)
        parts = result.split("\r")
        # <ASCII-MAC>, A entry, separator, B entry
        assert len(parts) == 4
        assert parts[0] == "<ASCII-MAC>"
        assert "Adams" in parts[1]
        assert parts[2] == ""  # blank paragraph separator
        assert "Baker" in parts[3]

    def test_no_separator_before_first(self):
        entries = [
            _entry(last_name="Adams", sort_key="adams", cat_nos=[1]),
        ]
        result = render_index_tagged_text(entries, CFG)
        parts = result.split("\r")
        assert len(parts) == 2  # header + one entry

    def test_no_separator_same_letter(self):
        entries = [
            _entry(last_name="Adams", sort_key="adams", cat_nos=[1]),
            _entry(last_name="Archer", sort_key="archer", cat_nos=[2]),
        ]
        result = render_index_tagged_text(entries, CFG)
        parts = result.split("\r")
        assert len(parts) == 3  # header + 2 entries, no separator

    def test_none_separator(self):
        cfg = IndexExportConfig(section_separator="none")
        entries = [
            _entry(last_name="Adams", sort_key="adams", cat_nos=[1]),
            _entry(last_name="Baker", sort_key="baker", cat_nos=[2]),
        ]
        result = render_index_tagged_text(entries, cfg)
        parts = result.split("\r")
        # No separator injected between groups
        assert len(parts) == 3  # header + 2 entries

    def test_column_break_separator(self):
        cfg = IndexExportConfig(
            section_separator="column_break", section_separator_style="Spacer"
        )
        entries = [
            _entry(last_name="Adams", sort_key="adams", cat_nos=[1]),
            _entry(last_name="Baker", sort_key="baker", cat_nos=[2]),
        ]
        result = render_index_tagged_text(entries, cfg)
        parts = result.split("\r")
        assert "<pstyle:Spacer><cnxc:Column>" in parts[2]


class TestLetterHeading:
    def test_heading_disabled_by_default(self):
        entries = [
            _entry(last_name="Adams", sort_key="adams", cat_nos=[1]),
            _entry(last_name="Baker", sort_key="baker", cat_nos=[2]),
        ]
        result = render_index_tagged_text(entries, CFG)
        # No standalone "A" or "B" heading lines
        parts = result.split("\r")
        assert not any(
            p.strip() in ("<pstyle:Index Text>A", "<pstyle:Index Text>B") for p in parts
        )

    def test_heading_enabled_uses_entry_style(self):
        cfg = IndexExportConfig(letter_heading_enabled=True)
        entries = [
            _entry(last_name="Adams", sort_key="adams", cat_nos=[1]),
            _entry(last_name="Baker", sort_key="baker", cat_nos=[2]),
        ]
        result = render_index_tagged_text(entries, cfg)
        parts = result.split("\r")
        # "A" heading before Adams
        assert "<pstyle:Index Text>A" in parts
        # "B" heading before Baker (after separator)
        assert "<pstyle:Index Text>B" in parts

    def test_heading_with_custom_style(self):
        cfg = IndexExportConfig(
            letter_heading_enabled=True,
            letter_heading_style="Index Letter",
        )
        entries = [
            _entry(last_name="Adams", sort_key="adams", cat_nos=[1]),
            _entry(last_name="Baker", sort_key="baker", cat_nos=[2]),
        ]
        result = render_index_tagged_text(entries, cfg)
        parts = result.split("\r")
        assert "<pstyle:Index Letter>A" in parts
        assert "<pstyle:Index Letter>B" in parts

    def test_heading_single_letter_group(self):
        cfg = IndexExportConfig(letter_heading_enabled=True)
        entries = [
            _entry(last_name="Adams", sort_key="adams", cat_nos=[1]),
            _entry(last_name="Allen", sort_key="allen", cat_nos=[2]),
        ]
        result = render_index_tagged_text(entries, cfg)
        parts = result.split("\r")
        # Only one heading "A", no "B"
        assert parts.count("<pstyle:Index Text>A") == 1
        assert not any(p.endswith(">B") for p in parts)

    def test_heading_with_no_separator(self):
        cfg = IndexExportConfig(
            letter_heading_enabled=True,
            section_separator="none",
        )
        entries = [
            _entry(last_name="Adams", sort_key="adams", cat_nos=[1]),
            _entry(last_name="Baker", sort_key="baker", cat_nos=[2]),
        ]
        result = render_index_tagged_text(entries, cfg)
        parts = result.split("\r")
        # Headings present even with no separator
        assert "<pstyle:Index Text>A" in parts
        assert "<pstyle:Index Text>B" in parts
        # No blank separator lines between groups
        assert "" not in parts[1:]  # no empty parts after header
