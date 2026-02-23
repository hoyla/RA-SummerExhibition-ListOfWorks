"""Tests for the index override resolution service."""

import pytest

from backend.app.services.index_override_service import (
    resolve_index_artist,
    build_index_name,
    EffectiveIndexArtist,
)


# ---------------------------------------------------------------------------
# Minimal stub classes to avoid needing real ORM objects
# ---------------------------------------------------------------------------


class _FakeArtist:
    def __init__(self, **kwargs):
        self.title = kwargs.get("title")
        self.first_name = kwargs.get("first_name")
        self.last_name = kwargs.get("last_name")
        self.quals = kwargs.get("quals")
        self.company = kwargs.get("company")
        self.second_artist = kwargs.get("second_artist")
        self.raw_first_name = kwargs.get("raw_first_name")
        self.raw_last_name = kwargs.get("raw_last_name")
        self.is_ra_member = kwargs.get("is_ra_member", False)
        self.is_company = kwargs.get("is_company", False)
        self.sort_key = kwargs.get("sort_key", "")
        self.include_in_export = kwargs.get("include_in_export", True)


class _FakeOverride:
    def __init__(self, **kwargs):
        self.is_company_override = kwargs.get("is_company_override")
        self.first_name_override = kwargs.get("first_name_override")
        self.last_name_override = kwargs.get("last_name_override")
        self.title_override = kwargs.get("title_override")
        self.quals_override = kwargs.get("quals_override")
        self.second_artist_override = kwargs.get("second_artist_override")


class _FakeKnownArtist:
    def __init__(self, **kwargs):
        self.resolved_first_name = kwargs.get("resolved_first_name")
        self.resolved_last_name = kwargs.get("resolved_last_name")
        self.resolved_quals = kwargs.get("resolved_quals")
        self.resolved_second_artist = kwargs.get("resolved_second_artist")
        self.resolved_is_company = kwargs.get("resolved_is_company")


# ---------------------------------------------------------------------------
# Tests — no override, no known artist
# ---------------------------------------------------------------------------


class TestResolveNoOverride:
    def test_uses_auto_detected_values(self):
        artist = _FakeArtist(
            first_name="Roger",
            last_name="Adams",
            is_company=False,
        )
        eff = resolve_index_artist(artist, None)
        assert eff.is_company is False
        assert eff.is_company_auto is False
        assert eff.first_name == "Roger"
        assert eff.last_name == "Adams"

    def test_auto_company_preserved(self):
        artist = _FakeArtist(last_name="AKT II", is_company=True)
        eff = resolve_index_artist(artist, None)
        assert eff.is_company is True
        assert eff.is_company_auto is True


class TestResolveWithOverride:
    def test_override_true(self):
        artist = _FakeArtist(
            first_name="Roger",
            last_name="Adams",
            is_company=False,
        )
        override = _FakeOverride(is_company_override=True)
        eff = resolve_index_artist(artist, override)
        assert eff.is_company is True
        assert eff.is_company_auto is False  # baseline unchanged

    def test_override_false(self):
        artist = _FakeArtist(last_name="AKT II", is_company=True)
        override = _FakeOverride(is_company_override=False)
        eff = resolve_index_artist(artist, override)
        assert eff.is_company is False
        assert eff.is_company_auto is True

    def test_override_none_means_no_override(self):
        artist = _FakeArtist(last_name="AKT II", is_company=True)
        override = _FakeOverride(is_company_override=None)
        eff = resolve_index_artist(artist, override)
        assert eff.is_company is True  # falls back to auto
        assert eff.is_company_auto is True

    def test_other_fields_passed_through(self):
        artist = _FakeArtist(
            title="Sir",
            first_name="Roger",
            last_name="Adams",
            quals="CBE",
            company=None,
            is_ra_member=True,
            sort_key="adams roger",
            include_in_export=False,
        )
        override = _FakeOverride(is_company_override=True)
        eff = resolve_index_artist(artist, override)
        assert eff.title == "Sir"
        assert eff.first_name == "Roger"
        assert eff.last_name == "Adams"
        assert eff.quals == "CBE"
        assert eff.is_ra_member is True
        assert eff.include_in_export is False

    def test_override_first_name(self):
        artist = _FakeArtist(first_name="Roger", last_name="Adams")
        override = _FakeOverride(first_name_override="Rodger")
        eff = resolve_index_artist(artist, override)
        assert eff.first_name == "Rodger"
        assert eff.index_name == "Adams, Rodger"

    def test_override_last_name(self):
        artist = _FakeArtist(first_name="Roger", last_name="Adams")
        override = _FakeOverride(last_name_override="Addams")
        eff = resolve_index_artist(artist, override)
        assert eff.last_name == "Addams"
        assert eff.sort_key == "addams roger"

    def test_override_title(self):
        artist = _FakeArtist(first_name="David", last_name="Adjaye", title="Sir")
        override = _FakeOverride(title_override="Lord")
        eff = resolve_index_artist(artist, override)
        assert eff.title == "Lord"
        assert "Lord David" in eff.index_name

    def test_override_quals(self):
        artist = _FakeArtist(first_name="Cornelia", last_name="Parker", quals="CBE")
        override = _FakeOverride(quals_override="CBE RA")
        eff = resolve_index_artist(artist, override)
        assert eff.quals == "CBE RA"
        assert "cbe ra" in eff.index_name

    def test_override_second_artist(self):
        artist = _FakeArtist(
            first_name="Adam",
            last_name="Caruso",
            second_artist="and Peter St John",
        )
        override = _FakeOverride(second_artist_override="and P. St John")
        eff = resolve_index_artist(artist, override)
        assert eff.second_artist == "and P. St John"
        assert "and P. St John" in eff.index_name

    def test_override_clear_with_empty_string(self):
        """Empty string in override means 'clear this field'."""
        artist = _FakeArtist(first_name="Roger", last_name="Adams", quals="CBE")
        override = _FakeOverride(quals_override="")
        eff = resolve_index_artist(artist, override)
        assert eff.quals is None

    def test_override_beats_known_artist(self):
        """User override takes priority over known artist for text fields."""
        artist = _FakeArtist(first_name="Roger", last_name="Adams")
        known = _FakeKnownArtist(resolved_first_name="Roger A.")
        override = _FakeOverride(first_name_override="R.")
        eff = resolve_index_artist(artist, override, known)
        assert eff.first_name == "R."  # override wins over known artist


# ---------------------------------------------------------------------------
# Tests — known artist resolution
# ---------------------------------------------------------------------------


class TestResolveWithKnownArtist:
    def test_company_override(self):
        """Boyd & Evans: known artist sets company, clears first_name."""
        artist = _FakeArtist(
            first_name=None,  # multi-artist parsing may have cleared this
            last_name="Boyd",
            second_artist="& Evans",
            is_company=True,
        )
        known = _FakeKnownArtist(
            resolved_first_name="",
            resolved_last_name="Boyd & Evans",
            resolved_second_artist="",
            resolved_is_company=True,
        )
        eff = resolve_index_artist(artist, None, known)
        assert eff.last_name == "Boyd & Evans"
        assert eff.first_name is None
        assert eff.second_artist is None  # cleared by empty string
        assert eff.is_company is True
        assert eff.index_name == "Boyd & Evans"
        assert eff.sort_key == "boyd & evans"

    def test_multi_artist_split(self):
        """Caruso: known artist splits name and adds second artist."""
        artist = _FakeArtist(
            first_name=None,
            last_name="Adam Caruso and Peter St John",
            quals="RA",
            is_company=False,
            is_ra_member=True,
        )
        known = _FakeKnownArtist(
            resolved_first_name="Adam",
            resolved_last_name="Caruso",
            resolved_second_artist="and Peter St John",
        )
        eff = resolve_index_artist(artist, None, known)
        assert eff.first_name == "Adam"
        assert eff.last_name == "Caruso"
        assert eff.second_artist == "and Peter St John"
        assert eff.quals == "RA"  # preserved from artist
        assert eff.sort_key == "caruso adam"
        assert eff.index_name == "Caruso, Adam ra, and Peter St John"

    def test_known_none_means_keep_normalised(self):
        """None in known_artist fields means 'keep normalised value'."""
        artist = _FakeArtist(
            first_name="Roger",
            last_name="Adams",
            quals="CBE",
        )
        known = _FakeKnownArtist(
            resolved_first_name=None,
            resolved_last_name=None,
            resolved_quals=None,
        )
        eff = resolve_index_artist(artist, None, known)
        assert eff.first_name == "Roger"
        assert eff.last_name == "Adams"
        assert eff.quals == "CBE"

    def test_known_empty_string_clears_field(self):
        """Empty string in known_artist fields means 'clear to None'."""
        artist = _FakeArtist(
            first_name="Boyd",
            last_name="& Evans",
        )
        known = _FakeKnownArtist(
            resolved_first_name="",  # clear
        )
        eff = resolve_index_artist(artist, None, known)
        assert eff.first_name is None

    def test_override_beats_known_artist_for_company(self):
        """User override takes priority over known artist for is_company."""
        artist = _FakeArtist(
            last_name="SomeName",
            is_company=False,
        )
        known = _FakeKnownArtist(resolved_is_company=True)
        override = _FakeOverride(is_company_override=False)
        eff = resolve_index_artist(artist, override, known)
        assert eff.is_company is False  # override wins

    def test_known_artist_company_sets_company_field(self):
        """When known artist makes an entry a company, company field is populated."""
        artist = _FakeArtist(
            first_name=None,
            last_name="Boyd",
            company=None,
        )
        known = _FakeKnownArtist(
            resolved_last_name="Boyd & Evans",
            resolved_is_company=True,
        )
        eff = resolve_index_artist(artist, None, known)
        assert eff.company == "Boyd & Evans"

    def test_zatorski_company(self):
        """Zatorski + Zatorski: known artist resolves to company."""
        artist = _FakeArtist(
            first_name="Zatorski",
            last_name="+ Zatorski",
            is_company=False,
        )
        known = _FakeKnownArtist(
            resolved_first_name="",
            resolved_last_name="Zatorski + Zatorski",
            resolved_is_company=True,
        )
        eff = resolve_index_artist(artist, None, known)
        assert eff.last_name == "Zatorski + Zatorski"
        assert eff.first_name is None
        assert eff.is_company is True
        assert eff.sort_key == "zatorski + zatorski"
        assert eff.index_name == "Zatorski + Zatorski"


# ---------------------------------------------------------------------------
# Tests — index_name computation
# ---------------------------------------------------------------------------


class TestBuildIndexName:
    def test_simple(self):
        assert (
            build_index_name("Adams", "Roger", None, None, None, False)
            == "Adams, Roger"
        )

    def test_with_quals(self):
        name = build_index_name("Parker", "Cornelia", None, "CBE RA", None, False)
        assert name == "Parker, Cornelia cbe ra"

    def test_with_title(self):
        name = build_index_name("Adjaye", "David", "Sir", "OM OBE RA", None, False)
        assert name == "Adjaye, Sir David om obe ra"

    def test_company(self):
        assert build_index_name("AKT II", None, None, None, None, True) == "AKT II"

    def test_single_name_ra(self):
        name = build_index_name(None, "Assemble", None, "RA", None, False)
        assert name == "Assemble ra"

    def test_second_artist(self):
        name = build_index_name(
            "Caruso", "Adam", None, "RA", "and Peter St John", False
        )
        assert name == "Caruso, Adam ra, and Peter St John"

    def test_company_partnership(self):
        assert (
            build_index_name("Boyd & Evans", None, None, None, None, True)
            == "Boyd & Evans"
        )

    def test_company_ignores_second_artist(self):
        """A company should never show a second_artist suffix — the full name
        is already in last_name.  Regression test for Boyd & Evans showing as
        'Boyd & Evans, & Evans'."""
        assert (
            build_index_name("Boyd & Evans", None, None, None, "& Evans", True)
            == "Boyd & Evans"
        )

    def test_empty(self):
        assert build_index_name(None, None, None, None, None, False) == ""


# ---------------------------------------------------------------------------
# Tests — sort key recomputation
# ---------------------------------------------------------------------------


class TestSortKeyRecomputation:
    def test_sort_key_from_resolved_values(self):
        """Sort key should be based on resolved (not normalised) values."""
        artist = _FakeArtist(
            first_name=None,
            last_name="Boyd",
            sort_key="boyd",
        )
        known = _FakeKnownArtist(
            resolved_last_name="Boyd & Evans",
        )
        eff = resolve_index_artist(artist, None, known)
        assert eff.sort_key == "boyd & evans"

    def test_sort_key_without_known_artist(self):
        """Without known artist, sort key stays based on normalised values."""
        artist = _FakeArtist(
            first_name="Roger",
            last_name="Adams",
            sort_key="adams roger",
        )
        eff = resolve_index_artist(artist, None)
        assert eff.sort_key == "adams roger"
