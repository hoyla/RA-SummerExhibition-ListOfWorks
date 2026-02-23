"""Tests for the index override resolution service."""

import pytest

from backend.app.services.index_override_service import (
    resolve_index_artist,
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
        self.is_ra_member = kwargs.get("is_ra_member", False)
        self.is_company = kwargs.get("is_company", False)
        self.sort_key = kwargs.get("sort_key", "")
        self.include_in_export = kwargs.get("include_in_export", True)


class _FakeOverride:
    def __init__(self, is_company_override=None):
        self.is_company_override = is_company_override


# ---------------------------------------------------------------------------
# Tests
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
        assert eff.sort_key == "adams roger"
        assert eff.include_in_export is False
