"""Tests for the attributed import diff engine (services/import_diff.py).

Unit tests drive ``diff_states`` with hand-built state dicts to pin each
attribution cause (source / normalisation / override) and each pairing case
(unchanged, content edit, renumber, add/remove). One integration test feeds it
real serialised states from ``serialize_import_state`` to confirm the live
shape round-trips.
"""

import io
import uuid as _uuid

import pytest
from openpyxl import Workbook

from backend.app.services.import_diff import diff_states

# --------------------------------------------------------------------------- #
# Builders for unit tests
# --------------------------------------------------------------------------- #

_OVERRIDE_COLS = [
    "title_override",
    "title_cased_override",
    "artist_name_override",
    "artist_honorifics_override",
    "price_numeric_override",
    "price_text_override",
    "edition_total_override",
    "edition_price_numeric_override",
    "artwork_override",
    "medium_override",
    "notes",
]


def _override(**kw):
    """A full override dict (all columns present, defaulting to None) — mirrors
    the full-column serialisation a real snapshot produces."""
    d = {c: None for c in _OVERRIDE_COLS}
    d.update(kw)
    return d


def _work(
    work_id,
    cat_no,
    *,
    raw_title=None,
    raw_artist=None,
    raw_medium=None,
    raw_price=None,
    raw_edition=None,
    raw_artwork=None,
    raw_gallery="G1",
    title=None,
    title_cased=None,
    artist_name=None,
    artist_honorifics=None,
    price_numeric=None,
    price_text=None,
    edition_total=None,
    edition_price_numeric=None,
    artwork=None,
    medium=None,
    include_in_export=True,
    override=None,
):
    return {
        "id": work_id,
        "raw_cat_no": cat_no,
        "raw_gallery": raw_gallery,
        "raw_title": raw_title,
        "raw_artist": raw_artist,
        "raw_medium": raw_medium,
        "raw_price": raw_price,
        "raw_edition": raw_edition,
        "raw_artwork": raw_artwork,
        "title": title,
        "title_cased": title_cased,
        "artist_name": artist_name,
        "artist_honorifics": artist_honorifics,
        "price_numeric": price_numeric,
        "price_text": price_text,
        "edition_total": edition_total,
        "edition_price_numeric": edition_price_numeric,
        "artwork": artwork,
        "medium": medium,
        "include_in_export": include_in_export,
        "override": override,
        "warnings": [],
    }


def _state(*works, section="G1"):
    return {
        "version": 1,
        "sections": [{"id": "s1", "name": section, "position": 1, "works": list(works)}],
        "import_warnings": [],
    }


def _changed_field(diff, cat_no, field):
    """Return the change dict for a given field of the work whose NEW cat_no
    matches, or None."""
    for c in diff["changed"]:
        if c["new"]["cat_no"] == cat_no or c["old"]["cat_no"] == cat_no:
            for f in c["fields"]:
                if f["field"] == field:
                    return f
    return None


# --------------------------------------------------------------------------- #
# Unchanged
# --------------------------------------------------------------------------- #


def test_identical_states_no_changes():
    s = _state(_work("a", "1", raw_title="Sunset", title="Sunset", artist_name="Jane"))
    diff = diff_states(s, s)
    assert diff["has_changes"] is False
    assert diff["unchanged_count"] == 1
    assert diff["counts"] == {"changed": 0, "added": 0, "removed": 0, "unchanged": 1}


# --------------------------------------------------------------------------- #
# Attribution causes
# --------------------------------------------------------------------------- #


def test_source_change_is_attributed_to_source():
    # Same cat-no, title typo fixed in the spreadsheet. Fingerprint differs, so
    # it pairs by cat-no (pass 2) and the title change is attributed to source.
    old = _state(_work("a", "1", raw_title="Suset", title="Suset", artist_name="Jane"))
    new = _state(_work("b", "1", raw_title="Sunset", title="Sunset", artist_name="Jane"))
    diff = diff_states(old, new)
    assert diff["counts"]["changed"] == 1
    assert diff["changed"][0]["via"] == "cat_no"
    f = _changed_field(diff, "1", "title")
    assert f["old"] == "Suset" and f["new"] == "Sunset"
    assert f["causes"] == ["source"]


def test_normalisation_drift_is_attributed_to_normalisation():
    # Raw identical (so fingerprint matches, pass 1), but the normalised medium
    # moved — e.g. a text-substitution rule was added between the two states.
    old = _state(_work("a", "1", raw_title="X", title="X", raw_medium="oil", medium="oil"))
    new = _state(_work("b", "1", raw_title="X", title="X", raw_medium="oil", medium="Oil"))
    diff = diff_states(old, new)
    assert diff["changed"][0]["via"] == "fingerprint"
    f = _changed_field(diff, "1", "medium")
    assert f["old"] == "oil" and f["new"] == "Oil"
    assert f["causes"] == ["normalisation"]


def test_override_change_is_attributed_to_override():
    old = _state(_work("a", "1", raw_title="X", title="X", artist_name="Jane"))
    new = _state(
        _work(
            "b",
            "1",
            raw_title="X",
            title="X",
            artist_name="Jane",
            override=_override(title_override="Custom Title"),
        )
    )
    diff = diff_states(old, new)
    assert diff["changed"][0]["via"] == "fingerprint"
    f = _changed_field(diff, "1", "title")
    assert f["old"] == "X" and f["new"] == "Custom Title"
    assert f["causes"] == ["override"]


def test_include_in_export_toggle_is_reported():
    old = _state(_work("a", "1", raw_title="X", title="X", include_in_export=True))
    new = _state(_work("b", "1", raw_title="X", title="X", include_in_export=False))
    diff = diff_states(old, new)
    f = _changed_field(diff, "1", "include_in_export")
    assert f["old"] is True and f["new"] is False
    assert f["causes"] == ["override"]


# --------------------------------------------------------------------------- #
# Pairing cases
# --------------------------------------------------------------------------- #


def test_added_and_removed():
    old = _state(
        _work("a", "1", raw_title="Sunset", title="Sunset"),
        _work("b", "2", raw_title="Dawn", title="Dawn"),
    )
    new = _state(
        _work("c", "1", raw_title="Sunset", title="Sunset"),
        _work("d", "3", raw_title="Noon", title="Noon"),
    )
    diff = diff_states(old, new)
    assert diff["counts"]["unchanged"] == 1  # cat 1 unchanged
    assert [a["cat_no"] for a in diff["added"]] == ["3"]
    assert [r["cat_no"] for r in diff["removed"]] == ["2"]


def test_renumber_pairs_by_fingerprint_and_reports_cat_no_change():
    # An insertion pushes "Noon" from cat 3 to cat 4; a brand-new work takes
    # cat 3. Fingerprint pairs Noon 3->4 (renumber); the new work is an add.
    old = _state(
        _work("a", "1", raw_title="Sunset", title="Sunset"),
        _work("b", "3", raw_title="Noon", title="Noon", artist_name="Alice"),
    )
    new = _state(
        _work("c", "1", raw_title="Sunset", title="Sunset"),
        _work("d", "3", raw_title="Brand New", title="Brand New", artist_name="Bob"),
        _work("e", "4", raw_title="Noon", title="Noon", artist_name="Alice"),
    )
    diff = diff_states(old, new)
    # Noon paired by fingerprint, cat-no change 3 -> 4 surfaced as source.
    noon = next(c for c in diff["changed"] if c["new"]["title"] == "Noon")
    assert noon["via"] == "fingerprint"
    catf = next(f for f in noon["fields"] if f["field"] == "cat_no")
    assert catf["old"] == "3" and catf["new"] == "4" and catf["causes"] == ["source"]
    # The brand-new cat 3 is an addition, nothing removed.
    assert [a["cat_no"] for a in diff["added"]] == ["3"]
    assert diff["removed"] == []


def test_section_move_is_reported():
    old = _state(_work("a", "1", raw_title="X", title="X"), section="Gallery A")
    new = _state(_work("b", "1", raw_title="X", title="X"), section="Gallery B")
    diff = diff_states(old, new)
    f = _changed_field(diff, "1", "section")
    assert f["old"] == "Gallery A" and f["new"] == "Gallery B"
    assert f["causes"] == ["source"]


# --------------------------------------------------------------------------- #
# Integration: real serialised states
# --------------------------------------------------------------------------- #

client = pytest.fixture(name="client")(lambda client_lenient: client_lenient)

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
HEADERS = ["Cat No", "Gallery", "Title", "Artist", "Price", "Edition", "Artwork", "Medium"]


def _xlsx(rows):
    wb = Workbook()
    ws = wb.active
    ws.append(HEADERS)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def test_diff_over_real_serialised_states(client, db_session):
    from backend.app.services.import_snapshot import serialize_import_state

    rows = [
        [1, "Gallery A", "Sunset", "Jane Doe", "500", None, None, "Oil"],
        [2, "Gallery A", "Dawn", "John Smith RA", "1000", None, None, "Acrylic"],
    ]
    r = client.post("/import", files={"file": ("orig.xlsx", _xlsx(rows), XLSX_MIME)})
    import_id = r.json()["import_id"]
    iid = _uuid.UUID(import_id)

    old_state = serialize_import_state(iid, db_session)

    # Apply an override to cat 1 and exclude cat 2.
    sections = client.get(f"/imports/{import_id}/sections").json()
    works = {w["raw_cat_no"]: w for s in sections for w in s["works"]}
    client.put(
        f"/imports/{import_id}/works/{works['1']['id']}/override",
        json={"title_override": "Sunset (Revised)"},
    )
    client.patch(f"/imports/{import_id}/works/{works['2']['id']}/exclude?exclude=true")

    db_session.expire_all()
    new_state = serialize_import_state(iid, db_session)

    diff = diff_states(old_state, new_state)
    assert diff["has_changes"] is True
    title_change = _changed_field(diff, "1", "title")
    assert title_change["new"] == "Sunset (Revised)"
    assert title_change["causes"] == ["override"]
    incl_change = _changed_field(diff, "2", "include_in_export")
    assert incl_change["old"] is True and incl_change["new"] is False
