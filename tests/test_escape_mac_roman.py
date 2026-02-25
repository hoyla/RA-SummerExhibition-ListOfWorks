"""Unit tests for escape_for_mac_roman — character mapping and InDesign escapes."""

import pytest

from backend.app.services.export_renderer import escape_for_mac_roman


class TestEscapeForMacRomanAscii:
    """Pure ASCII should pass through unmodified."""

    def test_empty_string(self):
        assert escape_for_mac_roman("") == ""

    def test_plain_ascii(self):
        assert escape_for_mac_roman("Hello World") == "Hello World"

    def test_digits_and_punctuation(self):
        text = "Cat 123 — £5,000 (NFS)"
        # Both em-dash (U+2014) and £ (U+00A3) are valid Mac Roman chars
        result = escape_for_mac_roman(text)
        assert result == text  # everything passes through unchanged

    def test_newlines_and_tabs(self):
        assert escape_for_mac_roman("line1\nline2\ttab") == "line1\nline2\ttab"


class TestEscapeForMacRomanAccented:
    """Mac Roman includes many Western European accented characters."""

    @pytest.mark.parametrize(
        "char",
        ["é", "ñ", "ü", "ö", "à", "â", "ç", "ê", "î", "ô", "û"],
    )
    def test_mac_roman_accented_chars_pass_through(self, char):
        assert escape_for_mac_roman(char) == char

    def test_accented_artist_name(self):
        assert escape_for_mac_roman("José García") == "José García"


class TestEscapeForMacRomanUnicode:
    """Characters outside Mac Roman get the InDesign <0x####> escape."""

    def test_em_dash_is_mac_roman(self):
        # U+2014 (em-dash) is byte 0xD1 in Mac Roman — passes through
        assert escape_for_mac_roman("\u2014") == "\u2014"

    def test_en_dash(self):
        # en-dash U+2013 is in Mac Roman (0xD1), should pass through
        assert escape_for_mac_roman("\u2013") == "\u2013"

    def test_chinese_character(self):
        assert escape_for_mac_roman("作") == "<0x4F5C>"

    def test_emoji(self):
        assert escape_for_mac_roman("🎨") == "<0x1F3A8>"

    def test_mixed_text(self):
        result = escape_for_mac_roman("Art by Ö — 作品")
        # Ö and em-dash are Mac Roman; CJK chars are not
        assert result == "Art by Ö — <0x4F5C><0x54C1>"

    def test_zero_width_joiner(self):
        """U+200D (ZWJ) is not in Mac Roman."""
        assert escape_for_mac_roman("\u200d") == "<0x200D>"


class TestEscapeForMacRomanRoundtrip:
    """The result should be encodable as Mac Roman without error."""

    @pytest.mark.parametrize(
        "text",
        [
            "Hello",
            "José García — untitled",
            "作品 by 田中",
            "Price: £5,000",
            "Mixed: é ñ 🎨 — ∞",
        ],
    )
    def test_result_encodes_to_mac_roman(self, text):
        escaped = escape_for_mac_roman(text)
        # Should not raise UnicodeEncodeError
        escaped.encode("mac_roman")

    def test_escape_format_is_hex(self):
        """Escaped characters use <0xHHHH> format (uppercase hex, zero-padded)."""
        result = escape_for_mac_roman("\u4f5c")
        assert result == "<0x4F5C>"
        # 4 hex digits minimum
        result2 = escape_for_mac_roman("\u00ff")
        # U+00FF (ÿ) IS in Mac Roman, so it shouldn't be escaped
        assert result2 == "ÿ"


class TestEscapeForMacRomanEdgeCases:
    def test_null_like_char(self):
        # U+0000 is a control character — handle without crashing
        result = escape_for_mac_roman("\x00")
        # Null is technically encodable in mac_roman
        assert result == "\x00"

    def test_long_string_performance(self):
        """Shouldn't choke on long strings."""
        text = "abcé" * 10_000
        result = escape_for_mac_roman(text)
        assert len(result) == 40_000
