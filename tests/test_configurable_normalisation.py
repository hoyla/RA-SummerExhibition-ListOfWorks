"""Tests for admin-configurable normalisation rules.

Covers three layers:
  - the service primitives (edition-suppression threshold, literal text
    substitutions) and the warnings they raise;
  - the /config endpoint round-trip and validation;
  - the wiring fix — that a *saved* config is actually applied at import time
    (previously it silently fell back to defaults).
"""

import io
import uuid
from types import SimpleNamespace

import pytest
from openpyxl import Workbook

from backend.app.models.work_model import Work
from backend.app.services.normalisation_service import (
    apply_text_substitutions,
    collect_work_warnings,
    normalise_work,
    parse_edition,
)


# ---------------------------------------------------------------------------
# Edition-suppression threshold
# ---------------------------------------------------------------------------


def test_default_threshold_keeps_edition_of_1():
    # Default behaviour (0): "edition of 1" is a real, kept edition.
    total, price = parse_edition("Edition of 1 at £50")
    assert total == 1
    assert price == 50


def test_default_threshold_still_suppresses_edition_of_0():
    total, price = parse_edition("Edition of 0 at £0.00")
    assert total is None and price is None


def test_threshold_1_suppresses_edition_of_1():
    total, price = parse_edition("Edition of 1 at £50", suppress_max=1)
    assert total is None and price is None


def test_threshold_1_leaves_real_editions_untouched():
    # An edition of 6 is a genuine edition; the threshold must not touch it.
    total, price = parse_edition("Edition of 6 at £3,900.00", suppress_max=1)
    assert total == 6
    assert price == 3900


# ---------------------------------------------------------------------------
# Literal text substitutions
# ---------------------------------------------------------------------------


def test_substitution_is_literal_and_space_sensitive():
    """A spaced-hyphen rule must change " - " but not the hyphen in a
    hyphenated word."""
    subs = [{"find": " - ", "replace": " – ", "fields": ["title"]}]
    out = apply_text_substitutions("Sunrise - dusk over double-barrelled", subs, "title")
    assert out == "Sunrise – dusk over double-barrelled"


def test_substitution_respects_field_scope():
    subs = [{"find": "...", "replace": "…", "fields": ["title"]}]
    # Applies to title…
    assert apply_text_substitutions("Wait...", subs, "title") == "Wait…"
    # …but not to a field that isn't in scope.
    assert apply_text_substitutions("Wait...", subs, "medium") == "Wait..."


def test_substitutions_apply_in_order():
    subs = [
        {"find": "ae", "replace": "æ", "fields": ["title"]},
        {"find": "æ", "replace": "ae", "fields": ["title"]},
    ]
    # Second rule reverses the first.
    assert apply_text_substitutions("aether", subs, "title") == "aether"


def test_blank_find_is_skipped():
    subs = [{"find": "", "replace": "X", "fields": ["title"]}]
    assert apply_text_substitutions("hello", subs, "title") == "hello"


# ---------------------------------------------------------------------------
# normalise_work integration
# ---------------------------------------------------------------------------


def _raw_work(**kwargs):
    defaults = dict(
        raw_cat_no="1",
        raw_gallery="Gallery A",
        raw_title=None,
        raw_artist=None,
        raw_price=None,
        raw_edition=None,
        raw_artwork=None,
        raw_medium=None,
        title=None,
        artist_name=None,
        artist_honorifics=None,
        price_numeric=None,
        price_text=None,
        edition_total=None,
        edition_price_numeric=None,
        artwork=None,
        medium=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_normalise_work_applies_substitutions_to_scoped_fields():
    work = _raw_work(raw_title="Wait...", raw_medium="Oil...")
    subs = [{"find": "...", "replace": "…", "fields": ["title", "medium"]}]
    normalise_work(work, text_substitutions=subs)
    assert work.title == "Wait…"
    assert work.medium == "Oil…"


def test_normalise_work_substitution_skips_unscoped_field():
    work = _raw_work(raw_title="Wait...", raw_medium="Oil...")
    subs = [{"find": "...", "replace": "…", "fields": ["title"]}]
    normalise_work(work, text_substitutions=subs)
    assert work.title == "Wait…"
    assert work.medium == "Oil..."  # medium not in scope


def test_normalise_work_substitution_can_target_artist():
    work = _raw_work(raw_artist="Jane... Doe")
    subs = [{"find": "...", "replace": "…", "fields": ["artist"]}]
    normalise_work(work, text_substitutions=subs)
    assert work.artist_name == "Jane… Doe"


def test_normalise_work_edition_threshold_applied():
    work = _raw_work(raw_edition="Edition of 1 at £50", raw_price="100")
    normalise_work(work, edition_suppress_max=1)
    assert work.edition_total is None
    assert work.edition_price_numeric is None
    # Work's own price is untouched.
    assert work.price_numeric == 100


def test_normalise_work_does_not_mutate_raw():
    work = _raw_work(raw_title="Wait...", raw_edition="Edition of 1")
    normalise_work(
        work,
        edition_suppress_max=1,
        text_substitutions=[{"find": "...", "replace": "…", "fields": ["title"]}],
    )
    # raw_* stays canonical
    assert work.raw_title == "Wait..."
    assert work.raw_edition == "Edition of 1"


# ---------------------------------------------------------------------------
# Warnings: benign vs high-severity edition suppression
# ---------------------------------------------------------------------------


def _normalised_work(**kwargs):
    defaults = dict(
        raw_title="T",
        raw_artist="A",
        raw_medium=None,
        raw_price="100",
        raw_edition=None,
        title="T",
        artist_name="A",
        medium=None,
        price_numeric=100,
        price_text="100",
        edition_total=None,
        edition_price_numeric=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_edition_of_1_no_warning_at_default_threshold():
    # At threshold 0 the edition of 1 is kept, so no suppression warning.
    work = _normalised_work(
        raw_edition="Edition of 1 at £50", edition_total=1, edition_price_numeric=50
    )
    types = [t for t, _ in collect_work_warnings(work, edition_suppress_max=0)]
    assert "edition_suppressed" not in types
    assert "edition_suppressed_no_price" not in types


def test_edition_suppressed_is_benign_when_work_has_price():
    work = _normalised_work(
        raw_edition="Edition of 1 at £50",
        price_numeric=100,
        price_text="100",
        edition_total=None,  # suppressed by threshold 1
        edition_price_numeric=None,
    )
    types = [t for t, _ in collect_work_warnings(work, edition_suppress_max=1)]
    assert "edition_suppressed" in types
    assert "edition_suppressed_no_price" not in types


def test_edition_suppressed_no_price_is_high_when_it_was_the_only_price():
    # No work price of its own; the edition-of-1 price was all there was.
    work = _normalised_work(
        raw_price=None,
        raw_edition="Edition of 1 at £50",
        price_numeric=None,
        price_text="*",
        edition_total=None,
        edition_price_numeric=None,
    )
    warns = collect_work_warnings(work, edition_suppress_max=1)
    types = {t for t, _ in warns}
    assert "edition_suppressed_no_price" in types
    assert "edition_suppressed" not in types
    # The message names the recoverable price so an editor can restore it.
    msg = next(m for t, m in warns if t == "edition_suppressed_no_price")
    assert "50" in msg


def test_priceless_suppressed_edition_of_1_is_benign():
    # "Edition of 1" with no price and no work price → nothing lost, benign.
    work = _normalised_work(
        raw_price=None,
        raw_edition="Edition of 1",
        price_numeric=None,
        price_text="*",
        edition_total=None,
        edition_price_numeric=None,
    )
    types = {t for t, _ in collect_work_warnings(work, edition_suppress_max=1)}
    assert "edition_suppressed" in types
    assert "edition_suppressed_no_price" not in types


# ---------------------------------------------------------------------------
# /config round-trip and validation
# ---------------------------------------------------------------------------


def test_get_config_returns_new_defaults(client):
    cfg = client.get("/config").json()
    assert cfg["edition_suppress_max"] == 0
    assert any(
        s["find"] == "..." and s["replace"] == "…" for s in cfg["text_substitutions"]
    )


def test_put_config_round_trips_all_fields(client):
    body = {
        "honorific_tokens": ["RA"],
        "edition_suppress_max": 1,
        "text_substitutions": [
            {"find": " - ", "replace": " – ", "fields": ["title", "medium"]},
        ],
    }
    assert client.put("/config", json=body).status_code == 200
    cfg = client.get("/config").json()
    assert cfg["edition_suppress_max"] == 1
    assert cfg["text_substitutions"][0]["find"] == " - "  # spaces preserved
    assert cfg["text_substitutions"][0]["replace"] == " – "


def test_put_config_rejects_blank_find(client):
    body = {"text_substitutions": [{"find": "", "replace": "x", "fields": ["title"]}]}
    assert client.put("/config", json=body).status_code == 422


def test_put_config_rejects_unknown_field(client):
    body = {
        "text_substitutions": [{"find": "x", "replace": "y", "fields": ["nonsense"]}]
    }
    assert client.put("/config", json=body).status_code == 422


def test_put_config_rejects_out_of_range_threshold(client):
    assert client.put("/config", json={"edition_suppress_max": -1}).status_code == 422
    assert client.put("/config", json={"edition_suppress_max": 99}).status_code == 422


# ---------------------------------------------------------------------------
# Wiring: a saved config is actually applied at import (regression)
# ---------------------------------------------------------------------------

ALL_HEADERS = ["Cat No", "Gallery", "Title", "Artist", "Price", "Edition", "Artwork", "Medium"]


def _make_xlsx(rows):
    wb = Workbook()
    ws = wb.active
    ws.append(ALL_HEADERS)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _import(client, rows):
    r = client.post(
        "/import",
        files={
            "file": (
                "test.xlsx",
                _make_xlsx(rows),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["import_id"]


def test_saved_config_is_applied_on_import(client, db_session):
    """The bug fix: editing the normalisation config must change a subsequent
    import. A distinctive rule set proves the saved config (not defaults) is in
    force."""
    client.put(
        "/config",
        json={
            "honorific_tokens": ["RA"],
            "edition_suppress_max": 1,
            "text_substitutions": [
                {"find": "ZZZ", "replace": "QQQ", "fields": ["title"]}
            ],
        },
    )
    import_id = _import(
        client,
        [[1, "Gallery A", "Hello ZZZ", "Jane Doe", "100", "Edition of 1 at £50", None, "Oil"]],
    )
    work = (
        db_session.query(Work)
        .filter(Work.import_id == uuid.UUID(import_id))
        .first()
    )
    assert work.title == "Hello QQQ"  # substitution from saved config applied
    assert work.edition_total is None  # edition-of-1 suppressed per saved threshold
    assert work.price_numeric == 100  # work's own price stands


def test_default_substitution_applies_on_import_without_saved_config(client, db_session):
    """With no admin config, the shipped default (... → …) still applies."""
    import_id = _import(
        client,
        [[1, "Gallery A", "Wait...", "Jane Doe", "100", None, None, "Oil"]],
    )
    work = (
        db_session.query(Work)
        .filter(Work.import_id == uuid.UUID(import_id))
        .first()
    )
    assert work.title == "Wait…"
