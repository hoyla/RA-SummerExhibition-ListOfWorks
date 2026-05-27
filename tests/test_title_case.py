"""Title-casing: the derived `title_cased` field used by outputs (e.g. the LPG)
that want title case rather than the LOW's all-caps house style.

Best-effort conversion (the `titlecase` library + a callback for acronyms and
Roman numerals); the result is corrected per work via the title-case override.
"""

from types import SimpleNamespace

import pytest

from backend.app.services.normalisation_service import (
    DEFAULT_TITLE_CASE_EXCEPTIONS,
    normalise_work,
    to_title_case,
)
from backend.app.services.override_service import resolve_effective_work


# ---------------------------------------------------------------------------
# to_title_case
# ---------------------------------------------------------------------------


def test_all_caps_becomes_title_case():
    assert to_title_case("WHAT DO ANIMALS DREAM OF?") == "What Do Animals Dream Of?"


def test_small_words_stay_lower():
    assert to_title_case("THE POSSIBILITY OF AN ISLAND") == "The Possibility of an Island"


def test_roman_numerals_preserved_uppercase():
    assert to_title_case("UNTITLED VIII") == "Untitled VIII"
    assert to_title_case("STUDY XIV") == "Study XIV"


def test_roman_denylist_avoids_common_word():
    # "MIX" matches the Roman pattern but is a real word — not uppercased.
    assert to_title_case("THE MIX") == "The Mix"


def test_exceptions_preserve_casing():
    out = to_title_case("PORTRAIT FOR THE USA", ["USA"])
    assert "USA" in out
    assert out == "Portrait for the USA"


def test_exceptions_default_includes_ra():
    out = to_title_case("HOMAGE TO RA", DEFAULT_TITLE_CASE_EXCEPTIONS)
    assert out.endswith("RA")


def test_intentional_mixed_case_preserved():
    # Not all-caps input → titlecase preserves deliberate styling.
    assert to_title_case("the iPhone diaries") == "The iPhone Diaries"


def test_empty_and_none_pass_through():
    assert to_title_case("") == ""
    assert to_title_case(None) is None


# ---------------------------------------------------------------------------
# normalise_work populates title_cased
# ---------------------------------------------------------------------------


def _raw_work(**kwargs):
    defaults = dict(
        raw_cat_no="1", raw_gallery="G", raw_title=None, raw_artist=None,
        raw_price=None, raw_edition=None, raw_artwork=None, raw_medium=None,
        title=None, title_cased=None, artist_name=None, artist_honorifics=None,
        price_numeric=None, price_text=None, edition_total=None,
        edition_price_numeric=None, artwork=None, medium=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_normalise_work_sets_title_cased():
    work = _raw_work(raw_title="WHAT DO ANIMALS DREAM OF?")
    normalise_work(work)
    assert work.title == "WHAT DO ANIMALS DREAM OF?"  # source casing untouched
    assert work.title_cased == "What Do Animals Dream Of?"  # derived alongside


def test_normalise_work_title_cased_uses_custom_exceptions():
    work = _raw_work(raw_title="MADE IN THE ACME WORKSHOP")
    normalise_work(work, title_case_exceptions=["ACME"])
    assert "ACME" in work.title_cased


def test_normalise_work_title_cased_none_when_no_title():
    work = _raw_work(raw_title=None)
    normalise_work(work)
    assert work.title_cased is None


# ---------------------------------------------------------------------------
# resolve_effective_work carries title_cased + its override
# ---------------------------------------------------------------------------


def _work(**kw):
    d = dict(
        raw_cat_no="1", title="WHAT DO ANIMALS DREAM OF?",
        title_cased="What Do Animals Dream Of?", artist_name="A",
        artist_honorifics=None, price_numeric=None, price_text="*",
        edition_total=None, edition_price_numeric=None, artwork=None,
        medium=None, include_in_export=True,
    )
    d.update(kw)
    return SimpleNamespace(**d)


def _override(**kw):
    d = dict(
        title_override=None, title_cased_override=None, artist_name_override=None,
        artist_honorifics_override=None, price_numeric_override=None,
        price_text_override=None, edition_total_override=None,
        edition_price_numeric_override=None, artwork_override=None,
        medium_override=None, notes=None,
    )
    d.update(kw)
    return SimpleNamespace(**d)


def test_effective_title_cased_from_work():
    ew = resolve_effective_work(_work(), None)
    assert ew.title_cased == "What Do Animals Dream Of?"


def test_title_cased_override_wins():
    ew = resolve_effective_work(
        _work(), _override(title_cased_override="What Do Animals Dream OF?")
    )
    assert ew.title_cased == "What Do Animals Dream OF?"
    # The plain title is unaffected by the cased override.
    assert ew.title == "WHAT DO ANIMALS DREAM OF?"


# ---------------------------------------------------------------------------
# Route level: override round-trip and config exceptions
# ---------------------------------------------------------------------------


def _seed_one_work(db):
    from backend.app.models.import_model import Import
    from backend.app.models.section_model import Section
    from backend.app.models.work_model import Work

    imp = Import(filename="tc.xlsx", product_type="list_of_works")
    db.add(imp)
    db.commit()
    db.refresh(imp)
    sec = Section(import_id=imp.id, name="G", position=1)
    db.add(sec)
    db.commit()
    db.refresh(sec)
    work = Work(
        import_id=imp.id, section_id=sec.id, position_in_section=1,
        raw_cat_no="1", title="WHAT DO ANIMALS DREAM OF?",
        title_cased="What Do Animals Dream Of?", artist_name="A",
        include_in_export=True,
    )
    db.add(work)
    db.commit()
    db.refresh(work)
    return imp, work


def test_title_cased_override_endpoint_roundtrip(client, db_session):
    imp, work = _seed_one_work(db_session)
    r = client.put(
        f"/imports/{imp.id}/works/{work.id}/override",
        json={"title_cased_override": "What Do Animals Dream OF?"},
    )
    assert r.status_code == 200
    assert r.json()["title_cased_override"] == "What Do Animals Dream OF?"
    got = client.get(f"/imports/{imp.id}/works/{work.id}/override").json()
    assert got["title_cased_override"] == "What Do Animals Dream OF?"


def test_config_roundtrips_title_case_exceptions(client):
    client.put("/config", json={"title_case_exceptions": ["RA", "ZZZ"]})
    assert "ZZZ" in client.get("/config").json()["title_case_exceptions"]
