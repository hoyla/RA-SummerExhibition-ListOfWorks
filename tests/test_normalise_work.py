"""Unit tests for normalise_work — the orchestrator that ties all normalisation together."""

import pytest

from backend.app.services.normalisation_service import normalise_work


# ---------------------------------------------------------------------------
# Lightweight stand-in for a Work model row (avoids needing a DB session)
# ---------------------------------------------------------------------------


class FakeWork:
    """Mimics the Work SQLAlchemy model's relevant attributes."""

    def __init__(
        self,
        raw_artist=None,
        raw_price=None,
        raw_edition=None,
        raw_artwork=None,
        raw_title=None,
        raw_medium=None,
    ):
        # Raw layer
        self.raw_artist = raw_artist
        self.raw_price = raw_price
        self.raw_edition = raw_edition
        self.raw_artwork = raw_artwork
        self.raw_title = raw_title
        self.raw_medium = raw_medium

        # Normalised layer (set by normalise_work)
        self.artist_name = None
        self.artist_honorifics = None
        self.price_numeric = None
        self.price_text = None
        self.edition_total = None
        self.edition_price_numeric = None
        self.artwork = None
        self.title = None
        self.medium = None


# ---------------------------------------------------------------------------
# Artist normalisation via normalise_work
# ---------------------------------------------------------------------------


class TestNormaliseWorkArtist:
    def test_plain_name(self):
        w = FakeWork(raw_artist="John Smith")
        normalise_work(w)
        assert w.artist_name == "John Smith"
        assert w.artist_honorifics is None

    def test_name_with_honorifics(self):
        w = FakeWork(raw_artist="John Smith RA")
        normalise_work(w)
        assert w.artist_name == "John Smith"
        assert w.artist_honorifics == "RA"

    def test_multiple_honorifics(self):
        w = FakeWork(raw_artist="Jane Doe HON RA")
        normalise_work(w)
        assert w.artist_name == "Jane Doe"
        assert w.artist_honorifics == "HON RA"

    def test_no_artist(self):
        w = FakeWork(raw_artist=None)
        normalise_work(w)
        assert w.artist_name is None
        assert w.artist_honorifics is None

    def test_empty_artist(self):
        w = FakeWork(raw_artist="")
        normalise_work(w)
        assert w.artist_name is None
        assert w.artist_honorifics is None

    def test_custom_honorific_tokens(self):
        w = FakeWork(raw_artist="John Smith CBE")
        normalise_work(w, honorific_tokens=["CBE"])
        assert w.artist_name == "John Smith"
        assert w.artist_honorifics == "CBE"

    def test_single_name_no_split(self):
        w = FakeWork(raw_artist="Banksy")
        normalise_work(w)
        assert w.artist_name == "Banksy"
        assert w.artist_honorifics is None


# ---------------------------------------------------------------------------
# Price normalisation via normalise_work
# ---------------------------------------------------------------------------


class TestNormaliseWorkPrice:
    def test_numeric_price(self):
        w = FakeWork(raw_price="5000")
        normalise_work(w)
        assert w.price_numeric == 5000
        assert w.price_text == "5000"

    def test_price_with_currency(self):
        w = FakeWork(raw_price="£5,000")
        normalise_work(w)
        assert w.price_numeric == 5000

    def test_nfs(self):
        w = FakeWork(raw_price="NFS")
        normalise_work(w)
        assert w.price_numeric is None
        assert w.price_text == "NFS"

    def test_blank_price(self):
        w = FakeWork(raw_price=None)
        normalise_work(w)
        assert w.price_numeric is None
        assert w.price_text == "*"

    def test_asterisk_price(self):
        w = FakeWork(raw_price="*")
        normalise_work(w)
        assert w.price_numeric is None
        assert w.price_text == "*"


# ---------------------------------------------------------------------------
# Edition normalisation via normalise_work
# ---------------------------------------------------------------------------


class TestNormaliseWorkEdition:
    def test_full_edition(self):
        w = FakeWork(raw_edition="Edition of 25 at £500")
        normalise_work(w)
        assert w.edition_total == 25
        assert w.edition_price_numeric == 500

    def test_edition_no_price(self):
        w = FakeWork(raw_edition="Edition of 10")
        normalise_work(w)
        assert w.edition_total == 10
        assert w.edition_price_numeric is None

    def test_no_edition(self):
        w = FakeWork(raw_edition=None)
        normalise_work(w)
        assert w.edition_total is None
        assert w.edition_price_numeric is None

    def test_zero_edition(self):
        w = FakeWork(raw_edition="Edition of 0")
        normalise_work(w)
        assert w.edition_total is None
        assert w.edition_price_numeric is None


# ---------------------------------------------------------------------------
# Artwork, title, medium via normalise_work
# ---------------------------------------------------------------------------


class TestNormaliseWorkSimpleFields:
    def test_artwork_numeric(self):
        w = FakeWork(raw_artwork="42")
        normalise_work(w)
        assert w.artwork == 42

    def test_artwork_with_whitespace(self):
        w = FakeWork(raw_artwork="  42  ")
        normalise_work(w)
        assert w.artwork == 42

    def test_artwork_non_numeric(self):
        w = FakeWork(raw_artwork="N/A")
        normalise_work(w)
        assert w.artwork is None

    def test_artwork_none(self):
        w = FakeWork(raw_artwork=None)
        normalise_work(w)
        assert w.artwork is None

    def test_title_stripped(self):
        w = FakeWork(raw_title="  Sunset Over London  ")
        normalise_work(w)
        assert w.title == "Sunset Over London"

    def test_title_none(self):
        w = FakeWork(raw_title=None)
        normalise_work(w)
        assert w.title is None

    def test_medium_stripped(self):
        w = FakeWork(raw_medium="  Oil on canvas  ")
        normalise_work(w)
        assert w.medium == "Oil on canvas"

    def test_medium_none(self):
        w = FakeWork(raw_medium=None)
        normalise_work(w)
        assert w.medium is None


# ---------------------------------------------------------------------------
# Full orchestration — all fields set at once
# ---------------------------------------------------------------------------


class TestNormaliseWorkFull:
    def test_all_fields_together(self):
        w = FakeWork(
            raw_artist="Jane Doe RA",
            raw_price="£1,200",
            raw_edition="Edition of 5 at £300",
            raw_artwork="7",
            raw_title="  The Garden  ",
            raw_medium="  Watercolour  ",
        )
        normalise_work(w)

        assert w.artist_name == "Jane Doe"
        assert w.artist_honorifics == "RA"
        assert w.price_numeric == 1200
        assert w.edition_total == 5
        assert w.edition_price_numeric == 300
        assert w.artwork == 7
        assert w.title == "The Garden"
        assert w.medium == "Watercolour"

    def test_all_fields_none(self):
        w = FakeWork()
        normalise_work(w)

        assert w.artist_name is None
        assert w.artist_honorifics is None
        assert w.price_numeric is None
        assert w.price_text == "*"
        assert w.edition_total is None
        assert w.edition_price_numeric is None
        assert w.artwork is None
        assert w.title is None
        assert w.medium is None
