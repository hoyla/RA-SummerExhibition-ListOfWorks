"""
Tests for the cross-dataset comparison service and API endpoint.
"""

import uuid

import pytest

from backend.app.models.import_model import Import
from backend.app.models.work_model import Work
from backend.app.models.override_model import WorkOverride
from backend.app.models.index_artist_model import IndexArtist
from backend.app.models.index_cat_number_model import IndexCatNumber
from backend.app.models.index_override_model import IndexArtistOverride
from backend.app.models.known_artist_model import KnownArtist
from backend.app.models.section_model import Section
from backend.app.services.comparison_service import (
    MatchLevel,
    _compare_names,
    _extract_low_name_parts,
    _normalise_words,
    compare_datasets,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_low_import(db, works_data):
    """Seed a LoW import with works.

    works_data: list of (cat_no, artist_name, artist_honorifics)
    Returns import record.
    """
    imp = Import(filename="low.xlsx", product_type="list_of_works")
    db.add(imp)
    db.flush()

    section = Section(import_id=imp.id, name="Gallery A", position=1)
    db.add(section)
    db.flush()

    for i, (cat_no, artist_name, honorifics) in enumerate(works_data, 1):
        w = Work(
            import_id=imp.id,
            section_id=section.id,
            position_in_section=i,
            raw_cat_no=str(cat_no),
            raw_artist=f"{artist_name} {honorifics or ''}".strip(),
            artist_name=artist_name,
            artist_honorifics=honorifics,
            title=f"Work {cat_no}",
            include_in_export=True,
        )
        db.add(w)

    db.flush()
    return imp


def _seed_index_import(db, artists_data):
    """Seed an Index import with artists and cat numbers.

    artists_data: list of (first_name, last_name, quals, cat_nos, kwargs)
      where cat_nos is a list of int, and kwargs is optional dict with
      extra fields like title, is_company, courtesy values.
    Returns import record.
    """
    imp = Import(filename="index.xlsx", product_type="artists_index")
    db.add(imp)
    db.flush()

    for row_num, item in enumerate(artists_data, 2):
        if len(item) == 4:
            first_name, last_name, quals, cat_nos = item
            extra = {}
        else:
            first_name, last_name, quals, cat_nos, extra = item

        a = IndexArtist(
            import_id=imp.id,
            row_number=row_num,
            raw_first_name=first_name,
            raw_last_name=last_name,
            raw_quals=quals,
            first_name=first_name,
            last_name=last_name,
            quals=quals,
            title=extra.get("title"),
            is_ra_member=bool(quals and "ra" in quals.lower()),
            is_company=extra.get("is_company", False),
            company=extra.get("company"),
            sort_key=f"{(last_name or '').lower()} {(first_name or '').lower()}".strip(),
            include_in_export=True,
            artist1_ra_styled=extra.get("artist1_ra_styled", False),
            artist2_ra_styled=extra.get("artist2_ra_styled", False),
            artist3_ra_styled=extra.get("artist3_ra_styled", False),
        )
        db.add(a)
        db.flush()

        courtesies = extra.get("courtesies", {})
        for cn in cat_nos:
            cat = IndexCatNumber(
                artist_id=a.id,
                cat_no=cn,
                courtesy=courtesies.get(cn),
                source_row=row_num,
            )
            db.add(cat)

    db.flush()
    return imp


# ===========================================================================
# Unit tests: name parsing and comparison logic
# ===========================================================================


class TestNormaliseWords:
    def test_basic(self):
        assert _normalise_words("Hello, World") == {"hello", "world"}

    def test_none(self):
        assert _normalise_words(None) == set()

    def test_empty(self):
        assert _normalise_words("") == set()


class TestExtractLowNameParts:
    def test_standard_name(self):
        first, last, quals = _extract_low_name_parts("Ryan Gander", "RA")
        assert first == "Ryan"
        assert last == "Gander"
        assert quals == {"ra"}

    def test_single_name(self):
        first, last, quals = _extract_low_name_parts("Banksy", None)
        assert first == ""
        assert last == "Banksy"

    def test_multi_word_first_name(self):
        first, last, quals = _extract_low_name_parts("Bob and Roberta Smith", "RA")
        assert first == "Bob and Roberta"
        assert last == "Smith"

    def test_empty(self):
        first, last, quals = _extract_low_name_parts(None, None)
        assert first == ""
        assert last == ""

    def test_multiple_honorifics(self):
        first, last, quals = _extract_low_name_parts("Rebecca Salter", "CBE PRA")
        assert quals == {"cbe", "pra"}


class TestCompareNames:
    def test_exact_match(self):
        level, diffs = _compare_names(
            "Roger Adams", None, "Roger", "Adams", None, None, False
        )
        assert level == MatchLevel.exact

    def test_equivalent_same_words(self):
        """LoW 'Ryan Gander RA' vs Index first='Ryan' last='Gander' quals='RA'."""
        level, diffs = _compare_names(
            "Ryan Gander", "RA", "Ryan", "Gander", None, "RA", False
        )
        assert level in (MatchLevel.exact, MatchLevel.equivalent)

    def test_partial_extra_quals_in_index(self):
        """LoW 'Ryan Gander RA' vs Index 'Ryan Gander OBE RA'."""
        level, diffs = _compare_names(
            "Ryan Gander", "RA", "Ryan", "Gander", None, "OBE RA", False
        )
        assert level == MatchLevel.partial
        assert any("extra_quals_in_index" in d for d in diffs)

    def test_partial_title_in_index(self):
        """LoW 'Farshid Moussavi RA' vs Index title='Prof.' first='Farshid' last='Moussavi'."""
        level, diffs = _compare_names(
            "Farshid Moussavi", "RA", "Farshid", "Moussavi", "Prof.", "OBE RA", False
        )
        assert level == MatchLevel.partial

    def test_title_prefix_in_low(self):
        """LoW 'Dame Tracey Emin RA' vs Index title=None first='Tracey' last='Emin'."""
        # LoW includes title prefix, Index has it as structured title
        level, diffs = _compare_names(
            "Dame Tracey Emin", "RA", "Tracey", "Emin", "Dame", "DBE RA", False
        )
        assert level == MatchLevel.partial

    def test_company_match(self):
        level, diffs = _compare_names(
            "51 Architecture", None, None, "51 Architecture", None, None, True
        )
        assert level in (MatchLevel.exact, MatchLevel.equivalent)

    def test_no_match(self):
        level, diffs = _compare_names(
            "Alice Smith", None, "Bob", "Jones", None, None, False
        )
        assert level == MatchLevel.none

    def test_last_name_match_first_name_different(self):
        level, diffs = _compare_names(
            "Alice Smith", None, "Bob", "Smith", None, None, False
        )
        assert level == MatchLevel.partial
        assert "first_name_different" in diffs


# ===========================================================================
# Integration tests: compare_datasets with DB
# ===========================================================================


class TestCompareDatasets:
    def test_perfect_match(self, db_session):
        """Both datasets have the same cat numbers, names match."""
        low = _seed_low_import(
            db_session,
            [
                (1, "Roger Adams", None),
                (2, "Cornelia Parker", "CBE RA"),
            ],
        )
        idx = _seed_index_import(
            db_session,
            [
                ("Roger", "Adams", None, [1]),
                ("Cornelia", "Parker", "CBE RA", [2]),
            ],
        )
        db_session.commit()

        result = compare_datasets(db_session, low.id, idx.id)
        assert result.summary.total_low == 2
        assert result.summary.total_index == 2
        assert result.summary.in_both == 2
        assert result.summary.only_in_low == 0
        assert result.summary.only_in_index == 0
        # All should be exact or equivalent
        assert result.summary.match_none == 0

    def test_missing_in_index(self, db_session):
        """LoW has a cat number not in Index."""
        low = _seed_low_import(
            db_session,
            [
                (1, "Roger Adams", None),
                (2, "Cornelia Parker", "RA"),
            ],
        )
        idx = _seed_index_import(
            db_session,
            [
                ("Roger", "Adams", None, [1]),
            ],
        )
        db_session.commit()

        result = compare_datasets(db_session, low.id, idx.id)
        assert result.summary.only_in_low == 1
        entry = [e for e in result.entries if e.cat_no == 2][0]
        assert "missing_in_index" in entry.differences

    def test_missing_in_low(self, db_session):
        """Index has a cat number not in LoW."""
        low = _seed_low_import(
            db_session,
            [
                (1, "Roger Adams", None),
            ],
        )
        idx = _seed_index_import(
            db_session,
            [
                ("Roger", "Adams", None, [1]),
                ("Cornelia", "Parker", "RA", [2]),
            ],
        )
        db_session.commit()

        result = compare_datasets(db_session, low.id, idx.id)
        assert result.summary.only_in_index == 1
        entry = [e for e in result.entries if e.cat_no == 2][0]
        assert "missing_in_low" in entry.differences

    def test_name_mismatch(self, db_session):
        """Same cat number, completely different artist."""
        low = _seed_low_import(
            db_session,
            [
                (1, "Alice Smith", None),
            ],
        )
        idx = _seed_index_import(
            db_session,
            [
                ("Bob", "Jones", None, [1]),
            ],
        )
        db_session.commit()

        result = compare_datasets(db_session, low.id, idx.id)
        assert result.summary.match_none == 1

    def test_extra_quals_detected(self, db_session):
        """LoW has fewer quals than Index — partial match."""
        low = _seed_low_import(
            db_session,
            [
                (1, "Ryan Gander", "RA"),
            ],
        )
        idx = _seed_index_import(
            db_session,
            [
                ("Ryan", "Gander", "OBE RA", [1]),
            ],
        )
        db_session.commit()

        result = compare_datasets(db_session, low.id, idx.id)
        entry = result.entries[0]
        assert entry.match_level == MatchLevel.partial
        assert any("extra_quals_in_index" in d for d in entry.differences)

    def test_multi_cat_numbers_per_artist(self, db_session):
        """One Index artist has multiple cat numbers."""
        low = _seed_low_import(
            db_session,
            [
                (1, "Ryan Gander", "RA"),
                (2, "Ryan Gander", "RA"),
                (3, "Ryan Gander", "RA"),
            ],
        )
        idx = _seed_index_import(
            db_session,
            [
                ("Ryan", "Gander", "RA", [1, 2, 3]),
            ],
        )
        db_session.commit()

        result = compare_datasets(db_session, low.id, idx.id)
        assert result.summary.in_both == 3
        assert len(result.entries) == 3
        # All entries should reference the same index artist
        artist_ids = {e.index_artist_id for e in result.entries}
        assert len(artist_ids) == 1

    def test_courtesy_included(self, db_session):
        """Courtesy values from Index are included in the result."""
        low = _seed_low_import(
            db_session,
            [
                (100, "Roger Adams", None),
                (200, "Roger Adams", None),
            ],
        )
        idx = _seed_index_import(
            db_session,
            [
                (
                    "Roger",
                    "Adams",
                    None,
                    [100, 200],
                    {
                        "courtesies": {200: "(courtesy of Someone)"},
                    },
                ),
            ],
        )
        db_session.commit()

        result = compare_datasets(db_session, low.id, idx.id)
        entries = {e.cat_no: e for e in result.entries}
        assert entries[100].index_courtesy is None
        assert entries[200].index_courtesy == "(courtesy of Someone)"

    def test_overrides_reflected_in_low(self, db_session):
        """LoW override changes the artist name used in comparison."""
        low = _seed_low_import(
            db_session,
            [
                (1, "Misspelled Name", None),
            ],
        )
        idx = _seed_index_import(
            db_session,
            [
                ("Roger", "Adams", None, [1]),
            ],
        )
        db_session.commit()

        # Apply override to correct the LoW name
        work = db_session.query(Work).filter(Work.import_id == low.id).first()
        ovr = WorkOverride(
            work_id=work.id,
            artist_name_override="Roger Adams",
        )
        db_session.add(ovr)
        db_session.commit()

        result = compare_datasets(db_session, low.id, idx.id)
        entry = result.entries[0]
        assert entry.low_artist_name == "Roger Adams"
        assert entry.match_level in (MatchLevel.exact, MatchLevel.equivalent)

    def test_overrides_reflected_in_index(self, db_session):
        """Index override changes the name used in comparison."""
        low = _seed_low_import(
            db_session,
            [
                (1, "Roger Adams", None),
            ],
        )
        idx = _seed_index_import(
            db_session,
            [
                ("Wrong", "Name", None, [1]),
            ],
        )
        db_session.commit()

        # Apply override to correct the Index name
        artist = (
            db_session.query(IndexArtist)
            .filter(IndexArtist.import_id == idx.id)
            .first()
        )
        ovr = IndexArtistOverride(
            artist_id=artist.id,
            first_name_override="Roger",
            last_name_override="Adams",
        )
        db_session.add(ovr)
        db_session.commit()

        result = compare_datasets(db_session, low.id, idx.id)
        entry = result.entries[0]
        assert entry.index_first_name == "Roger"
        assert entry.index_last_name == "Adams"
        assert entry.match_level in (MatchLevel.exact, MatchLevel.equivalent)

    def test_known_artist_reflected(self, db_session):
        """Known artist lookup affects the resolved Index name."""
        low = _seed_low_import(
            db_session,
            [
                (1, "Roger Adams", "RA"),
            ],
        )
        idx = _seed_index_import(
            db_session,
            [
                ("Roger", "Adams", None, [1]),
            ],
        )
        # Add a known artist that adds quals
        ka = KnownArtist(
            match_first_name="Roger",
            match_last_name="Adams",
            resolved_first_name="Roger",
            resolved_last_name="Adams",
            resolved_quals="RA",
        )
        db_session.add(ka)
        db_session.commit()

        result = compare_datasets(db_session, low.id, idx.id)
        entry = result.entries[0]
        # After known artist resolution, quals should match
        assert entry.match_level in (MatchLevel.exact, MatchLevel.equivalent)

    def test_company_comparison(self, db_session):
        """Company name comparison works correctly."""
        low = _seed_low_import(
            db_session,
            [
                (1, "51 Architecture", None),
            ],
        )
        idx = _seed_index_import(
            db_session,
            [
                (
                    None,
                    "51 Architecture",
                    None,
                    [1],
                    {"is_company": True, "company": "51 Architecture"},
                ),
            ],
        )
        db_session.commit()

        result = compare_datasets(db_session, low.id, idx.id)
        entry = result.entries[0]
        assert entry.match_level in (MatchLevel.exact, MatchLevel.equivalent)

    def test_empty_datasets(self, db_session):
        """Both datasets empty — should return empty result."""
        low = Import(filename="low.xlsx", product_type="list_of_works")
        idx = Import(filename="index.xlsx", product_type="artists_index")
        db_session.add_all([low, idx])
        db_session.commit()

        result = compare_datasets(db_session, low.id, idx.id)
        assert result.summary.total_low == 0
        assert result.summary.total_index == 0
        assert len(result.entries) == 0

    def test_entries_sorted_by_cat_no(self, db_session):
        """Entries are returned in catalogue number order."""
        low = _seed_low_import(
            db_session,
            [
                (300, "Artist C", None),
                (100, "Artist A", None),
                (200, "Artist B", None),
            ],
        )
        idx = _seed_index_import(
            db_session,
            [
                ("Artist", "A", None, [100]),
                ("Artist", "B", None, [200]),
                ("Artist", "C", None, [300]),
            ],
        )
        db_session.commit()

        result = compare_datasets(db_session, low.id, idx.id)
        cat_nos = [e.cat_no for e in result.entries]
        assert cat_nos == [100, 200, 300]


# ===========================================================================
# API endpoint tests
# ===========================================================================


class TestCompareEndpoint:
    def test_success(self, client, db_session):
        """POST /compare returns structured comparison."""
        low = _seed_low_import(
            db_session,
            [
                (1, "Roger Adams", None),
            ],
        )
        idx = _seed_index_import(
            db_session,
            [
                ("Roger", "Adams", None, [1]),
            ],
        )
        db_session.commit()

        r = client.post(
            "/compare",
            params={"low_import_id": str(low.id), "index_import_id": str(idx.id)},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["summary"]["total_low"] == 1
        assert data["summary"]["total_index"] == 1
        assert data["summary"]["in_both"] == 1
        assert len(data["entries"]) == 1
        assert data["entries"][0]["cat_no"] == 1

    def test_low_import_not_found(self, client_lenient, db_session):
        """404 if LoW import doesn't exist."""
        idx = Import(filename="idx.xlsx", product_type="artists_index")
        db_session.add(idx)
        db_session.commit()

        r = client_lenient.post(
            "/compare",
            params={
                "low_import_id": str(uuid.uuid4()),
                "index_import_id": str(idx.id),
            },
        )
        assert r.status_code == 404

    def test_index_import_not_found(self, client_lenient, db_session):
        """404 if Index import doesn't exist."""
        low = Import(filename="low.xlsx", product_type="list_of_works")
        db_session.add(low)
        db_session.commit()

        r = client_lenient.post(
            "/compare",
            params={
                "low_import_id": str(low.id),
                "index_import_id": str(uuid.uuid4()),
            },
        )
        assert r.status_code == 404

    def test_wrong_product_type_for_low(self, client_lenient, db_session):
        """400 if LoW import is actually an artists_index."""
        imp1 = Import(filename="a.xlsx", product_type="artists_index")
        imp2 = Import(filename="b.xlsx", product_type="artists_index")
        db_session.add_all([imp1, imp2])
        db_session.commit()

        r = client_lenient.post(
            "/compare",
            params={
                "low_import_id": str(imp1.id),
                "index_import_id": str(imp2.id),
            },
        )
        assert r.status_code == 400

    def test_wrong_product_type_for_index(self, client_lenient, db_session):
        """400 if Index import is actually a list_of_works."""
        imp1 = Import(filename="a.xlsx", product_type="list_of_works")
        imp2 = Import(filename="b.xlsx", product_type="list_of_works")
        db_session.add_all([imp1, imp2])
        db_session.commit()

        r = client_lenient.post(
            "/compare",
            params={
                "low_import_id": str(imp1.id),
                "index_import_id": str(imp2.id),
            },
        )
        assert r.status_code == 400

    def test_response_includes_work_and_artist_ids(self, client, db_session):
        """Response entries include work_id and artist_id for deep-linking."""
        low = _seed_low_import(
            db_session,
            [
                (1, "Roger Adams", None),
            ],
        )
        idx = _seed_index_import(
            db_session,
            [
                ("Roger", "Adams", None, [1]),
            ],
        )
        db_session.commit()

        r = client.post(
            "/compare",
            params={"low_import_id": str(low.id), "index_import_id": str(idx.id)},
        )
        entry = r.json()["entries"][0]
        assert entry["low_work_id"] is not None
        assert entry["index_artist_id"] is not None

    def test_response_match_level_is_string(self, client, db_session):
        """match_level is serialised as a string value."""
        low = _seed_low_import(
            db_session,
            [
                (1, "Roger Adams", None),
            ],
        )
        idx = _seed_index_import(
            db_session,
            [
                ("Roger", "Adams", None, [1]),
            ],
        )
        db_session.commit()

        r = client.post(
            "/compare",
            params={"low_import_id": str(low.id), "index_import_id": str(idx.id)},
        )
        entry = r.json()["entries"][0]
        assert entry["match_level"] in ("exact", "equivalent", "partial", "none")
