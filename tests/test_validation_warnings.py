from types import SimpleNamespace

import pytest

from backend.app.services.normalisation_service import collect_work_warnings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_work(**kwargs) -> SimpleNamespace:
    """
    Return a fake normalised Work with sensible defaults.
    Override any field via keyword arguments.
    """
    defaults = dict(
        raw_title="Test Title",
        raw_artist="Test Artist",
        raw_price="£1,200.00",
        raw_edition=None,
        title="Test Title",
        artist_name="Test Artist",
        price_numeric=1200,
        price_text="1200",
        edition_total=None,
        edition_price_numeric=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# Clean work – no warnings
# ---------------------------------------------------------------------------


def test_clean_work_produces_no_warnings():
    work = make_work()
    assert collect_work_warnings(work) == []


# ---------------------------------------------------------------------------
# missing_title
# ---------------------------------------------------------------------------


def test_warns_missing_title_when_title_is_none():
    work = make_work(title=None)
    types = [w[0] for w in collect_work_warnings(work)]
    assert "missing_title" in types


def test_warns_missing_title_when_title_is_empty_string():
    work = make_work(title="")
    types = [w[0] for w in collect_work_warnings(work)]
    assert "missing_title" in types


# ---------------------------------------------------------------------------
# missing_artist
# ---------------------------------------------------------------------------


def test_warns_missing_artist_when_artist_name_is_none():
    work = make_work(artist_name=None)
    types = [w[0] for w in collect_work_warnings(work)]
    assert "missing_artist" in types


# ---------------------------------------------------------------------------
# missing_price
# ---------------------------------------------------------------------------


def test_warns_missing_price_when_price_text_is_placeholder():
    work = make_work(price_numeric=None, price_text="*")
    types = [w[0] for w in collect_work_warnings(work)]
    assert "missing_price" in types


def test_no_missing_price_warning_for_nfs():
    work = make_work(price_numeric=None, price_text="NFS")
    types = [w[0] for w in collect_work_warnings(work)]
    assert "missing_price" not in types


def test_no_missing_price_warning_for_numeric():
    work = make_work(price_numeric=3600, price_text="3600")
    types = [w[0] for w in collect_work_warnings(work)]
    assert "missing_price" not in types


# ---------------------------------------------------------------------------
# unrecognised_price
# ---------------------------------------------------------------------------


def test_warns_unrecognised_price_when_raw_value_is_not_parseable():
    work = make_work(
        raw_price="ENQUIRE",
        price_numeric=None,
        price_text="ENQUIRE",
    )
    types = [w[0] for w in collect_work_warnings(work)]
    assert "unrecognised_price" in types


def test_no_unrecognised_price_warning_for_nfs():
    work = make_work(
        raw_price="NFS",
        price_numeric=None,
        price_text="NFS",
    )
    types = [w[0] for w in collect_work_warnings(work)]
    assert "unrecognised_price" not in types


# ---------------------------------------------------------------------------
# edition_anomaly
# ---------------------------------------------------------------------------


def test_warns_edition_anomaly_when_raw_edition_unparseable():
    work = make_work(
        raw_edition="Unique",
        edition_total=None,
        edition_price_numeric=None,
    )
    types = [w[0] for w in collect_work_warnings(work)]
    assert "edition_anomaly" in types


def test_no_edition_anomaly_for_successfully_parsed_edition():
    work = make_work(
        raw_edition="Edition of 6 at £3,900.00",
        edition_total=6,
        edition_price_numeric=3900,
    )
    types = [w[0] for w in collect_work_warnings(work)]
    assert "edition_anomaly" not in types


# ---------------------------------------------------------------------------
# zero_edition_suppressed
# ---------------------------------------------------------------------------


def test_warns_zero_edition_suppressed():
    work = make_work(
        raw_edition="Edition of 0 at £0.00",
        edition_total=None,
        edition_price_numeric=None,
    )
    types = [w[0] for w in collect_work_warnings(work)]
    assert "zero_edition_suppressed" in types


def test_zero_edition_does_not_also_raise_anomaly():
    work = make_work(
        raw_edition="Edition of 0 at £0.00",
        edition_total=None,
        edition_price_numeric=None,
    )
    types = [w[0] for w in collect_work_warnings(work)]
    assert "edition_anomaly" not in types


# ---------------------------------------------------------------------------
# Warning message content
# ---------------------------------------------------------------------------


def test_warning_message_includes_raw_value():
    work = make_work(
        raw_price="ENQUIRE",
        price_numeric=None,
        price_text="ENQUIRE",
    )
    warnings = collect_work_warnings(work)
    messages = [w[1] for w in warnings]
    assert any("ENQUIRE" in m for m in messages)


# ---------------------------------------------------------------------------
# whitespace_trimmed
# ---------------------------------------------------------------------------


def test_warns_whitespace_trimmed_for_title():
    work = make_work(raw_title="  Test Title  ", title="Test Title")
    types = [w[0] for w in collect_work_warnings(work)]
    assert "whitespace_trimmed" in types


def test_warns_whitespace_trimmed_for_artist():
    work = make_work(raw_artist=" Test Artist ", artist_name="Test Artist")
    types = [w[0] for w in collect_work_warnings(work)]
    assert "whitespace_trimmed" in types


def test_warns_whitespace_trimmed_for_medium():
    work = make_work(raw_medium="  Oil on canvas ", medium="Oil on canvas")
    types = [w[0] for w in collect_work_warnings(work)]
    assert "whitespace_trimmed" in types


def test_no_whitespace_trimmed_when_raw_matches_normalised():
    work = make_work(raw_title="Test Title", title="Test Title")
    types = [w[0] for w in collect_work_warnings(work)]
    assert "whitespace_trimmed" not in types


def test_whitespace_trimmed_message_lists_fields():
    work = make_work(
        raw_title="  Test Title ",
        title="Test Title",
        raw_artist="  Test Artist",
        artist_name="Test Artist",
    )
    warnings = collect_work_warnings(work)
    msgs = {t: m for t, m in warnings}
    msg = msgs.get("whitespace_trimmed", "")
    assert "Title" in msg
    assert "Artist" in msg


def test_no_whitespace_trimmed_when_value_actually_changed():
    """If raw != norm and it's not just whitespace, should NOT be whitespace_trimmed."""
    work = make_work(raw_title="Old Title", title="New Title")
    types = [w[0] for w in collect_work_warnings(work)]
    assert "whitespace_trimmed" not in types
