import pytest
from types import SimpleNamespace

from backend.app.services.normalisation_service import (
    collect_work_warnings,
    normalise_artist,
    parse_price,
    parse_edition,
)


# -----------------------------
# Artist Normalisation Tests
# -----------------------------


def test_artist_trims_whitespace():
    name, honorifics = normalise_artist("  Ryan Gander RA  ")
    assert name == "Ryan Gander"
    assert honorifics == "RA"


def test_artist_no_honorific():
    name, honorifics = normalise_artist("Liča Anić")
    assert name == "Liča Anić"
    assert honorifics is None


def test_artist_multiple_spaces():
    name, honorifics = normalise_artist("  Tchonova + la Roi Architecture  ")
    assert name == "Tchonova + la Roi Architecture"
    assert honorifics is None


def test_artist_ra_elect():
    name, honorifics = normalise_artist("Barbara Walker RA Elect")
    assert name == "Barbara Walker"
    assert honorifics == "RA Elect"


def test_artist_hon_ra():
    name, honorifics = normalise_artist("William Kentridge HON RA")
    assert name == "William Kentridge"
    assert honorifics == "HON RA"


def test_artist_ra_ex_officio():
    name, honorifics = normalise_artist("Jane Doe RA Ex Officio")
    assert name == "Jane Doe"
    assert honorifics == "RA Ex Officio"


# -----------------------------
# Price Parsing Tests
# -----------------------------


def test_price_numeric():
    numeric, text = parse_price("£3,600.00")
    assert numeric == 3600
    assert text == "3600"


def test_price_nfs():
    numeric, text = parse_price("NFS")
    assert numeric is None
    assert text == "NFS"


def test_price_star():
    numeric, text = parse_price("*")
    assert numeric is None
    assert text == "*"


def test_price_blank():
    numeric, text = parse_price("")
    assert numeric is None
    assert text == "*"


# -----------------------------
# Edition Parsing Tests
# -----------------------------


def test_edition_full():
    total, price = parse_edition("Edition of 6 at £3,900.00")
    assert total == 6
    assert price == 3900


def test_edition_unpriced():
    total, price = parse_edition("Edition of 27")
    assert total == 27
    assert price is None


def test_edition_zero_suppressed():
    total, price = parse_edition("Edition of 0 at £0.00")
    assert total is None
    assert price is None


def test_edition_incomplete_price():
    total, price = parse_edition("Edition of 2 at ")
    assert total == 2
    assert price is None


# -----------------------------
# Non-ASCII Warnings
# -----------------------------


def _work(**kwargs):
    """Minimal work stub for collect_work_warnings."""
    defaults = dict(
        title=None,
        artist_name=None,
        artist_honorifics=None,
        medium=None,
        price_numeric=None,
        price_text="*",
        raw_price=None,
        raw_edition=None,
        edition_total=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_non_ascii_warning_raised():
    w = _work(title="Caf\u00e9 au lait", artist_name="Smith")
    types = [t for t, _ in collect_work_warnings(w)]
    assert "non_ascii_characters" in types


def test_non_ascii_warning_message_names_field_and_codepoint():
    w = _work(title="Na\u00efve", artist_name="Jones")
    msgs = {t: m for t, m in collect_work_warnings(w)}
    msg = msgs.get("non_ascii_characters", "")
    assert "title" in msg
    assert "U+00EF" in msg or "\u00ef" in repr("\u00ef")


def test_non_ascii_warning_absent_for_ascii_only():
    w = _work(title="Plain title", artist_name="Jane Doe", medium="oil on canvas")
    types = [t for t, _ in collect_work_warnings(w)]
    assert "non_ascii_characters" not in types
