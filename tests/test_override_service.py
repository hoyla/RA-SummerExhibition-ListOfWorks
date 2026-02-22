"""
Tests for override resolution service.
"""

from types import SimpleNamespace
from decimal import Decimal

import pytest

from backend.app.services.override_service import resolve_effective_work, EffectiveWork


def _make_work(**kwargs):
    defaults = dict(
        raw_cat_no="1",
        title="Original Title",
        artist_name="Original Artist",
        artist_honorifics="RA",
        price_numeric=Decimal("1000"),
        price_text="1000",
        edition_total=5,
        edition_price_numeric=Decimal("500"),
        artwork=None,
        medium="Oil on canvas",
        include_in_export=True,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_override(**kwargs):
    defaults = dict(
        title_override=None,
        artist_name_override=None,
        artist_honorifics_override=None,
        price_numeric_override=None,
        price_text_override=None,
        edition_total_override=None,
        edition_price_numeric_override=None,
        artwork_override=None,
        medium_override=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# ------------------------------------------------------------------
# No override – returns work values unchanged
# ------------------------------------------------------------------


def test_no_override_returns_work_values():
    work = _make_work()
    ew = resolve_effective_work(work, None)

    assert ew.title == "Original Title"
    assert ew.artist_name == "Original Artist"
    assert ew.artist_honorifics == "RA"
    assert ew.price_numeric == Decimal("1000")
    assert ew.price_text == "1000"
    assert ew.edition_total == 5
    assert ew.edition_price_numeric == Decimal("500")
    assert ew.medium == "Oil on canvas"
    assert ew.include_in_export is True


# ------------------------------------------------------------------
# Override replaces individual fields
# ------------------------------------------------------------------


def test_title_override_replaces_title():
    work = _make_work()
    override = _make_override(title_override="New Title")
    ew = resolve_effective_work(work, override)
    assert ew.title == "New Title"


def test_artist_name_override_replaces_artist():
    work = _make_work()
    override = _make_override(artist_name_override="New Artist")
    ew = resolve_effective_work(work, override)
    assert ew.artist_name == "New Artist"
    # Other fields unchanged
    assert ew.title == "Original Title"


def test_price_numeric_override_replaces_price():
    work = _make_work()
    override = _make_override(price_numeric_override=Decimal("2500"))
    ew = resolve_effective_work(work, override)
    assert ew.price_numeric == Decimal("2500")


def test_price_text_override_replaces_price_text():
    work = _make_work()
    override = _make_override(price_text_override="NFS")
    ew = resolve_effective_work(work, override)
    assert ew.price_text == "NFS"


def test_edition_total_override_replaces_edition():
    work = _make_work()
    override = _make_override(edition_total_override=10)
    ew = resolve_effective_work(work, override)
    assert ew.edition_total == 10
    # Price is still from work
    assert ew.edition_price_numeric == Decimal("500")


def test_medium_override_replaces_medium():
    work = _make_work()
    override = _make_override(medium_override="Print")
    ew = resolve_effective_work(work, override)
    assert ew.medium == "Print"


# ------------------------------------------------------------------
# None override fields fall back to work values
# ------------------------------------------------------------------


def test_null_override_fields_fall_back_to_work_values():
    work = _make_work()
    override = _make_override()  # all fields None
    ew = resolve_effective_work(work, override)

    assert ew.title == "Original Title"
    assert ew.artist_name == "Original Artist"
    assert ew.price_numeric == Decimal("1000")
    assert ew.edition_total == 5


# ------------------------------------------------------------------
# include_in_export is never overridden (lives on Work only)
# ------------------------------------------------------------------


def test_include_in_export_is_not_overridable():
    work = _make_work(include_in_export=False)
    override = _make_override(title_override="Overridden")
    ew = resolve_effective_work(work, override)
    assert ew.include_in_export is False


# ------------------------------------------------------------------
# raw_cat_no is never overridden
# ------------------------------------------------------------------


def test_raw_cat_no_is_always_from_work():
    work = _make_work(raw_cat_no="42")
    override = _make_override()
    ew = resolve_effective_work(work, override)
    assert ew.raw_cat_no == "42"
