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
        self.artist2_first_name = kwargs.get("artist2_first_name")
        self.artist2_last_name = kwargs.get("artist2_last_name")
        self.artist2_quals = kwargs.get("artist2_quals")
        self.artist3_first_name = kwargs.get("artist3_first_name")
        self.artist3_last_name = kwargs.get("artist3_last_name")
        self.artist3_quals = kwargs.get("artist3_quals")
        self.artist1_ra_styled = kwargs.get("artist1_ra_styled", False)
        self.artist2_ra_styled = kwargs.get("artist2_ra_styled", False)
        self.artist3_ra_styled = kwargs.get("artist3_ra_styled", False)
        self.artist2_shared_surname = kwargs.get("artist2_shared_surname", False)
        self.artist3_shared_surname = kwargs.get("artist3_shared_surname", False)
        self.raw_first_name = kwargs.get("raw_first_name")
        self.raw_last_name = kwargs.get("raw_last_name")
        self.raw_quals = kwargs.get("raw_quals")
        self.raw_company = kwargs.get("raw_company")
        self.raw_address = kwargs.get("raw_address")
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
        self.artist2_first_name_override = kwargs.get("artist2_first_name_override")
        self.artist2_last_name_override = kwargs.get("artist2_last_name_override")
        self.artist2_quals_override = kwargs.get("artist2_quals_override")
        self.artist3_first_name_override = kwargs.get("artist3_first_name_override")
        self.artist3_last_name_override = kwargs.get("artist3_last_name_override")
        self.artist3_quals_override = kwargs.get("artist3_quals_override")
        self.artist1_ra_styled_override = kwargs.get("artist1_ra_styled_override")
        self.artist2_ra_styled_override = kwargs.get("artist2_ra_styled_override")
        self.artist3_ra_styled_override = kwargs.get("artist3_ra_styled_override")
        self.artist2_shared_surname_override = kwargs.get("artist2_shared_surname_override")
        self.artist3_shared_surname_override = kwargs.get("artist3_shared_surname_override")
        self.company_override = kwargs.get("company_override")
        self.address_override = kwargs.get("address_override")


class _FakeKnownArtist:
    def __init__(self, **kwargs):
        self.resolved_first_name = kwargs.get("resolved_first_name")
        self.resolved_last_name = kwargs.get("resolved_last_name")
        self.resolved_title = kwargs.get("resolved_title")
        self.resolved_quals = kwargs.get("resolved_quals")
        self.resolved_artist2_first_name = kwargs.get("resolved_artist2_first_name")
        self.resolved_artist2_last_name = kwargs.get("resolved_artist2_last_name")
        self.resolved_artist2_quals = kwargs.get("resolved_artist2_quals")
        self.resolved_artist3_first_name = kwargs.get("resolved_artist3_first_name")
        self.resolved_artist3_last_name = kwargs.get("resolved_artist3_last_name")
        self.resolved_artist3_quals = kwargs.get("resolved_artist3_quals")
        self.resolved_artist1_ra_styled = kwargs.get("resolved_artist1_ra_styled")
        self.resolved_artist2_ra_styled = kwargs.get("resolved_artist2_ra_styled")
        self.resolved_artist3_ra_styled = kwargs.get("resolved_artist3_ra_styled")
        self.resolved_artist2_shared_surname = kwargs.get("resolved_artist2_shared_surname")
        self.resolved_artist3_shared_surname = kwargs.get("resolved_artist3_shared_surname")
        self.resolved_is_company = kwargs.get("resolved_is_company")
        self.resolved_company = kwargs.get("resolved_company")
        self.resolved_address = kwargs.get("resolved_address")


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
        assert "CBE RA" in eff.index_name

    def test_override_second_artist(self):
        artist = _FakeArtist(
            first_name="Adam",
            last_name="Caruso",
            artist2_first_name="Peter",
            artist2_last_name="St John",
        )
        override = _FakeOverride(
            artist2_first_name_override="P.", artist2_last_name_override="St John"
        )
        eff = resolve_index_artist(artist, override)
        assert eff.artist2_first_name == "P."
        assert eff.artist2_last_name == "St John"
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
            artist2_first_name=None,
            artist2_last_name="Evans",
            is_company=True,
        )
        known = _FakeKnownArtist(
            resolved_first_name="",
            resolved_last_name="Boyd & Evans",
            resolved_artist2_first_name="",
            resolved_artist2_last_name="",
            resolved_is_company=True,
        )
        eff = resolve_index_artist(artist, None, known)
        assert eff.last_name == "Boyd & Evans"
        assert eff.first_name is None
        assert eff.artist2_first_name is None  # cleared by empty string
        assert eff.artist2_last_name is None  # cleared by empty string
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
            artist1_ra_styled=True,
        )
        known = _FakeKnownArtist(
            resolved_first_name="Adam",
            resolved_last_name="Caruso",
            resolved_artist2_first_name="Peter",
            resolved_artist2_last_name="St John",
        )
        eff = resolve_index_artist(artist, None, known)
        assert eff.first_name == "Adam"
        assert eff.last_name == "Caruso"
        assert eff.artist2_first_name == "Peter"
        assert eff.artist2_last_name == "St John"
        assert eff.quals == "RA"  # preserved from artist
        assert eff.sort_key == "caruso adam"
        assert eff.index_name == "Caruso, Adam RA, and Peter St John"

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

    def test_known_artist_company_updates_stale_auto_company(self):
        """When the importer auto-derived company from a partial last_name,
        a known artist that changes last_name must also update company.

        Regression: Boyd & Evans had company='Boyd' (from import-time auto-
        detection on the partial last_name) instead of 'Boyd & Evans' (the
        known-artist-resolved last_name)."""
        artist = _FakeArtist(
            first_name=None,
            last_name="Boyd",
            company="Boyd",  # auto-derived during import from partial last_name
            is_company=True,
            raw_company=None,  # no explicit company in the spreadsheet
        )
        known = _FakeKnownArtist(
            resolved_first_name="",
            resolved_last_name="Boyd & Evans",
            resolved_is_company=True,
        )
        eff = resolve_index_artist(artist, None, known)
        assert eff.last_name == "Boyd & Evans"
        assert eff.company == "Boyd & Evans"
        assert eff.first_name is None

    def test_explicit_raw_company_preserved(self):
        """When the spreadsheet has an explicit company name, it should be
        preserved even if last_name changes."""
        artist = _FakeArtist(
            first_name=None,
            last_name="Boyd",
            company="The Boyd Evans Partnership",  # explicit in spreadsheet
            is_company=True,
            raw_company="The Boyd Evans Partnership",
        )
        known = _FakeKnownArtist(
            resolved_last_name="Boyd & Evans",
            resolved_is_company=True,
        )
        eff = resolve_index_artist(artist, None, known)
        assert eff.company == "The Boyd Evans Partnership"

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
            build_index_name(
                "Adams", "Roger", None, None, None, None, None, None, None, None, False
            )
            == "Adams, Roger"
        )

    def test_with_quals(self):
        name = build_index_name(
            "Parker",
            "Cornelia",
            None,
            "CBE RA",
            None,
            None,
            None,
            None,
            None,
            None,
            False,
        )
        assert name == "Parker, Cornelia CBE RA"

    def test_with_title(self):
        name = build_index_name(
            "Adjaye",
            "David",
            "Sir",
            "OM OBE RA",
            None,
            None,
            None,
            None,
            None,
            None,
            False,
        )
        assert name == "Adjaye, Sir David OM OBE RA"

    def test_company(self):
        assert (
            build_index_name(
                "AKT II", None, None, None, None, None, None, None, None, None, True
            )
            == "AKT II"
        )

    def test_single_name_ra(self):
        name = build_index_name(
            None, "Assemble", None, "RA", None, None, None, None, None, None, False
        )
        assert name == "Assemble RA"

    def test_second_artist(self):
        name = build_index_name(
            "Caruso",
            "Adam",
            None,
            "RA",
            "Peter",
            "St John",
            None,
            None,
            None,
            None,
            False,
        )
        assert name == "Caruso, Adam RA, and Peter St John"

    def test_company_partnership(self):
        assert (
            build_index_name(
                "Boyd & Evans",
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                True,
            )
            == "Boyd & Evans"
        )

    def test_company_ignores_second_artist(self):
        """A company should never show additional artists — the full name
        is already in last_name.  Regression test for Boyd & Evans showing as
        'Boyd & Evans, & Evans'."""
        assert (
            build_index_name(
                "Boyd & Evans",
                None,
                None,
                None,
                None,
                "Evans",
                None,
                None,
                None,
                None,
                True,
            )
            == "Boyd & Evans"
        )

    def test_empty(self):
        assert (
            build_index_name(
                None, None, None, None, None, None, None, None, None, None, False
            )
            == ""
        )


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


# ---------------------------------------------------------------------------
# Tests — company text and address overrides
# ---------------------------------------------------------------------------


class TestCompanyAndAddressOverrides:
    def test_raw_address_passes_through(self):
        """Without override or known artist, raw_address becomes address."""
        artist = _FakeArtist(
            first_name="Roger",
            last_name="Adams",
            raw_address="London",
        )
        eff = resolve_index_artist(artist, None)
        assert eff.address == "London"

    def test_known_artist_overrides_address(self):
        """Known artist resolved_address takes priority over raw_address."""
        artist = _FakeArtist(
            first_name="Roger",
            last_name="Adams",
            raw_address="London",
        )
        known = _FakeKnownArtist(resolved_address="Paris")
        eff = resolve_index_artist(artist, None, known)
        assert eff.address == "Paris"

    def test_override_address_takes_priority(self):
        """User override address takes highest priority."""
        artist = _FakeArtist(
            first_name="Roger",
            last_name="Adams",
            raw_address="London",
        )
        known = _FakeKnownArtist(resolved_address="Paris")
        ovr = _FakeOverride(address_override="Berlin")
        eff = resolve_index_artist(artist, ovr, known)
        assert eff.address == "Berlin"

    def test_known_artist_company_text(self):
        """Known artist resolved_company overrides auto-derived company."""
        artist = _FakeArtist(
            first_name="Boyd",
            last_name="& Evans",
            company="Boyd",
            is_company=True,
        )
        known = _FakeKnownArtist(
            resolved_last_name="Boyd & Evans",
            resolved_is_company=True,
            resolved_company="Boyd & Evans Partnership",
        )
        eff = resolve_index_artist(artist, None, known)
        assert eff.company == "Boyd & Evans Partnership"

    def test_override_company_text(self):
        """User override company_override takes highest priority."""
        artist = _FakeArtist(
            first_name="Boyd",
            last_name="& Evans",
            company="Boyd",
            is_company=True,
        )
        ovr = _FakeOverride(company_override="Boyd Evans Ltd")
        eff = resolve_index_artist(artist, ovr)
        assert eff.company == "Boyd Evans Ltd"

    def test_address_cleared_by_empty_string_override(self):
        """Empty-string override clears the address."""
        artist = _FakeArtist(
            first_name="Roger",
            last_name="Adams",
            raw_address="London",
        )
        ovr = _FakeOverride(address_override="")
        eff = resolve_index_artist(artist, ovr)
        assert eff.address is None

    def test_company_text_cleared_by_empty_string_override(self):
        """Empty-string override clears the company text."""
        artist = _FakeArtist(
            first_name="Roger",
            last_name="Adams",
            company="Acme Corp",
        )
        ovr = _FakeOverride(company_override="")
        eff = resolve_index_artist(artist, ovr)
        assert eff.company is None


class TestTitleFromKnownArtist:
    """Tests for resolved_title from known artist (layer 2)."""

    def test_known_artist_sets_title(self):
        """Known artist resolved_title applies when no override."""
        artist = _FakeArtist(first_name="David", last_name="Adjaye")
        known = _FakeKnownArtist(resolved_title="Sir")
        eff = resolve_index_artist(artist, None, known)
        assert eff.title == "Sir"

    def test_override_title_beats_known_artist_title(self):
        """User override title takes priority over known artist."""
        artist = _FakeArtist(first_name="David", last_name="Adjaye")
        known = _FakeKnownArtist(resolved_title="Sir")
        ovr = _FakeOverride(title_override="Lord")
        eff = resolve_index_artist(artist, ovr, known)
        assert eff.title == "Lord"

    def test_known_artist_title_in_index_name(self):
        """Title from known artist appears in the composite index name."""
        artist = _FakeArtist(first_name="David", last_name="Adjaye")
        known = _FakeKnownArtist(resolved_title="Sir")
        eff = resolve_index_artist(artist, None, known)
        assert "Sir David" in eff.index_name

    def test_known_artist_title_cleared_by_empty_override(self):
        """Empty-string override clears the title."""
        artist = _FakeArtist(first_name="David", last_name="Adjaye", title="Sir")
        ovr = _FakeOverride(title_override="")
        eff = resolve_index_artist(artist, ovr)
        assert eff.title is None


# ---------------------------------------------------------------------------
# Tests — shared surname
# ---------------------------------------------------------------------------


class TestSharedSurname:
    """Tests for the shared_surname flag on additional artists."""

    def test_defaults_false(self):
        """Without any overrides, shared_surname defaults to False."""
        artist = _FakeArtist(
            first_name="Lucy",
            last_name="Orta",
            artist2_first_name="Jorge",
            artist2_last_name="Orta",
        )
        eff = resolve_index_artist(artist, None)
        assert eff.artist2_shared_surname is False
        assert eff.artist3_shared_surname is False

    def test_normalised_value_passes_through(self):
        """When set on the normalised artist, shared_surname passes through."""
        artist = _FakeArtist(
            first_name="Lucy",
            last_name="Orta",
            artist2_first_name="Jorge",
            artist2_last_name="Orta",
            artist2_shared_surname=True,
        )
        eff = resolve_index_artist(artist, None)
        assert eff.artist2_shared_surname is True

    def test_known_artist_sets_shared_surname(self):
        """Known artist can set shared_surname for additional artists."""
        artist = _FakeArtist(
            first_name="Lucy",
            last_name="Orta",
            artist2_first_name="Jorge",
            artist2_last_name="Orta",
        )
        known = _FakeKnownArtist(resolved_artist2_shared_surname=True)
        eff = resolve_index_artist(artist, None, known)
        assert eff.artist2_shared_surname is True

    def test_override_sets_shared_surname(self):
        """User override can set shared_surname for additional artists."""
        artist = _FakeArtist(
            first_name="Lucy",
            last_name="Orta",
            artist2_first_name="Jorge",
            artist2_last_name="Orta",
        )
        ovr = _FakeOverride(artist2_shared_surname_override=True)
        eff = resolve_index_artist(artist, ovr)
        assert eff.artist2_shared_surname is True

    def test_override_beats_known_artist(self):
        """User override shared_surname takes priority over known artist."""
        artist = _FakeArtist(
            first_name="Lucy",
            last_name="Orta",
            artist2_first_name="Jorge",
            artist2_last_name="Orta",
        )
        known = _FakeKnownArtist(resolved_artist2_shared_surname=True)
        ovr = _FakeOverride(artist2_shared_surname_override=False)
        eff = resolve_index_artist(artist, ovr, known)
        assert eff.artist2_shared_surname is False

    def test_override_none_falls_through_to_known_artist(self):
        """None override means no override — falls through to known artist."""
        artist = _FakeArtist(
            first_name="Lucy",
            last_name="Orta",
            artist2_first_name="Jorge",
            artist2_last_name="Orta",
        )
        known = _FakeKnownArtist(resolved_artist2_shared_surname=True)
        ovr = _FakeOverride(artist2_shared_surname_override=None)
        eff = resolve_index_artist(artist, ovr, known)
        assert eff.artist2_shared_surname is True

    def test_artist3_shared_surname(self):
        """Shared surname works for artist 3 as well."""
        artist = _FakeArtist(
            first_name="Lucy",
            last_name="Orta",
            artist2_first_name="Jorge",
            artist2_last_name="Orta",
            artist3_first_name="Pablo",
            artist3_last_name="Orta",
        )
        ovr = _FakeOverride(artist3_shared_surname_override=True)
        eff = resolve_index_artist(artist, ovr)
        assert eff.artist3_shared_surname is True
        assert eff.artist2_shared_surname is False  # independent


class TestBuildIndexNameSharedSurname:
    """Tests for shared_surname in build_index_name()."""

    def test_two_artists_shared_surname(self):
        """Shared surname suppresses artist 2's last name."""
        name = build_index_name(
            "Orta", "Lucy", None, None,
            "Jorge", "Orta", None,
            None, None, None,
            False,
            artist2_shared_surname=True,
        )
        assert name == "Orta, Lucy, and Jorge"

    def test_two_artists_no_shared_surname(self):
        """Without shared surname, artist 2's last name is preserved."""
        name = build_index_name(
            "Orta", "Lucy", None, None,
            "Jorge", "Orta", None,
            None, None, None,
            False,
            artist2_shared_surname=False,
        )
        assert name == "Orta, Lucy, and Jorge Orta"

    def test_three_artists_all_shared_surname(self):
        """Three artists with shared surname — Oxford-comma style."""
        name = build_index_name(
            "Smith", "Melanie", None, None,
            "Michael", "Smith", None,
            "Anthony", "Smith", None,
            False,
            artist2_shared_surname=True,
            artist3_shared_surname=True,
        )
        assert name == "Smith, Melanie, Michael, and Anthony"

    def test_three_artists_only_artist2_shared(self):
        """Three artists, only artist 2 shares surname."""
        name = build_index_name(
            "Smith", "Melanie", None, None,
            "Michael", "Smith", None,
            "Anthony", "Jones", None,
            False,
            artist2_shared_surname=True,
            artist3_shared_surname=False,
        )
        assert name == "Smith, Melanie, Michael, and Anthony Jones"

    def test_shared_surname_with_quals(self):
        """Shared surname still shows quals."""
        name = build_index_name(
            "Orta", "Lucy", None, "RA",
            "Jorge", "Orta", "CBE",
            None, None, None,
            False,
            artist2_shared_surname=True,
        )
        assert name == "Orta, Lucy RA, and Jorge CBE"

    def test_shared_surname_in_resolved_index_name(self):
        """Shared surname propagates to the resolved index_name."""
        artist = _FakeArtist(
            first_name="Lucy",
            last_name="Orta",
            artist2_first_name="Jorge",
            artist2_last_name="Orta",
        )
        ovr = _FakeOverride(artist2_shared_surname_override=True)
        eff = resolve_index_artist(artist, ovr)
        assert eff.index_name == "Orta, Lucy, and Jorge"

    def test_three_artist_grammar_no_shared_surname(self):
        """Regression: 3-artist entries use Oxford-comma pattern (no 'and' before artist 2)."""
        name = build_index_name(
            "Eggerling", "Gabriele", None, None,
            "Dhruv", "Jadhav", None,
            "Hannah", "Puerta-Carlson", None,
            False,
        )
        assert name == "Eggerling, Gabriele, Dhruv Jadhav, and Hannah Puerta-Carlson"
