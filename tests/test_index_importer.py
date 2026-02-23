"""Tests for the Artists' Index importer."""

import pytest
from openpyxl import Workbook
from pathlib import Path

from backend.app.services.index_importer import (
    import_index_excel,
    IndexImportError,
    is_ra_member,
    build_sort_key,
    parse_cat_nos,
    detect_company,
    detect_multi_name,
    detect_quals_in_name,
)
from backend.app.models.index_artist_model import IndexArtist
from backend.app.models.index_cat_number_model import IndexCatNumber
from backend.app.models.known_artist_model import KnownArtist
from backend.app.models.validation_warning_model import ValidationWarning


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_workbook(rows, tmp_path: Path) -> str:
    """Create a minimal .xlsx with the standard Index headers and the given
    data rows.  Each row is a tuple of 7 values matching the column order:
    Title, First Name, Last Name, Quals, Company, Address 1, Cat Nos.
    """
    wb = Workbook()
    ws = wb.active
    ws.append(
        ["Title", "First Name", "Last Name", "Quals", "Company", "Address 1", "Cat Nos"]
    )
    for row in rows:
        ws.append(list(row))
    path = str(tmp_path / "index.xlsx")
    wb.save(path)
    return path


# ---------------------------------------------------------------------------
# Unit tests — helper functions
# ---------------------------------------------------------------------------


class TestIsRaMember:
    def test_plain_ra(self):
        assert is_ra_member("RA") is True

    def test_cbe_ra(self):
        assert is_ra_member("CBE RA") is True

    def test_hon_ra(self):
        assert is_ra_member("HON RA") is True

    def test_ppra(self):
        assert is_ra_member("PPRA") is True

    def test_ra_elect(self):
        assert is_ra_member("RA Elect") is True

    def test_no_quals(self):
        assert is_ra_member(None) is False
        assert is_ra_member("") is False

    def test_obe_only(self):
        assert is_ra_member("OBE") is False

    def test_cbe_only(self):
        assert is_ra_member("CBE") is False

    def test_ra_in_word(self):
        """RA must be whole word, not part of e.g. FRSA."""
        assert is_ra_member("FRSA") is False


class TestBuildSortKey:
    def test_simple(self):
        assert build_sort_key("Parker", "Cornelia") == "parker cornelia"

    def test_accents_stripped(self):
        assert build_sort_key("Abramović", "Marina") == "abramovic marina"

    def test_no_last_name(self):
        """First name used as primary sort when last name is absent."""
        assert build_sort_key(None, "Assemble") == "assemble"

    def test_both_none(self):
        assert build_sort_key(None, None) == ""


class TestParseCatNos:
    def test_semicolons(self):
        assert parse_cat_nos("101;205;318") == [101, 205, 318]

    def test_commas(self):
        assert parse_cat_nos("101,205,318") == [101, 205, 318]

    def test_single(self):
        assert parse_cat_nos("714") == [714]

    def test_integer_input(self):
        assert parse_cat_nos("714") == [714]

    def test_none(self):
        assert parse_cat_nos(None) == []

    def test_empty(self):
        assert parse_cat_nos("") == []

    def test_spaces(self):
        assert parse_cat_nos("101 ; 205 ; 318") == [101, 205, 318]


class TestDetectCompany:
    def test_company(self):
        assert detect_company(None, "AKT II", None) is True

    def test_individual(self):
        assert detect_company("Ron", "Arad", "RA") is False

    def test_single_name_with_quals(self):
        """Like 'Assemble RA' — has quals, so not a company."""
        assert detect_company(None, "Assemble", "RA") is False

    def test_no_name(self):
        assert detect_company(None, None, None) is False


class TestDetectMultiName:
    def test_and_separator(self):
        assert detect_multi_name("Louisa", "Hutton and Sauerbach") is True

    def test_ampersand_separator(self):
        assert detect_multi_name("Langlands", "Langlands & Bell") is True

    def test_with_separator(self):
        assert detect_multi_name("Jane with John", "Smith") is True

    def test_and_in_first_name(self):
        assert detect_multi_name("Louisa and Matthias", "Hutton") is True

    def test_no_separator(self):
        assert detect_multi_name("Roger", "Adams") is False

    def test_none_values(self):
        assert detect_multi_name(None, None) is False

    def test_anderson_not_flagged(self):
        """'and' inside a word like 'Anderson' should not trigger."""
        assert detect_multi_name("Ronnie", "Anderson") is False

    def test_sandy_not_flagged(self):
        assert detect_multi_name("Sandy", "Grant") is False


class TestDetectQualsInName:
    def test_obe_in_first_name(self):
        assert detect_quals_in_name("Louisa OBE", "Hutton") is not None

    def test_ra_in_last_name(self):
        assert detect_quals_in_name("Cornelia", "Parker RA") is not None

    def test_cbe_in_first_name(self):
        result = detect_quals_in_name("John CBE", "Smith")
        assert result is not None
        assert result.upper() == "CBE"

    def test_no_quals_in_name(self):
        assert detect_quals_in_name("Roger", "Adams") is None

    def test_none_values(self):
        assert detect_quals_in_name(None, None) is None

    def test_frsa_in_name(self):
        assert detect_quals_in_name("John FRSA", "Smith") is not None

    def test_partial_match_not_flagged(self):
        """Words containing qual tokens as substrings should not match."""
        assert detect_quals_in_name("Cbegins", "Obelix") is None


# ---------------------------------------------------------------------------
# Integration tests — full import
# ---------------------------------------------------------------------------


class TestImportBasic:
    def test_simple_artist(self, db_session, tmp_path):
        path = _make_workbook(
            [
                (None, "Roger", "Adams", None, None, None, "1266;1276"),
            ],
            tmp_path,
        )

        imp = import_index_excel(path, db_session)
        assert imp.product_type == "artists_index"

        artists = db_session.query(IndexArtist).filter_by(import_id=imp.id).all()
        assert len(artists) == 1
        a = artists[0]
        assert a.last_name == "Adams"
        assert a.first_name == "Roger"
        assert a.is_ra_member is False
        assert a.is_company is False

        cat_nums = (
            db_session.query(IndexCatNumber)
            .filter_by(artist_id=a.id)
            .order_by(IndexCatNumber.cat_no)
            .all()
        )
        assert [c.cat_no for c in cat_nums] == [1266, 1276]
        assert all(c.courtesy is None for c in cat_nums)

    def test_ra_member(self, db_session, tmp_path):
        path = _make_workbook(
            [
                ("Sir", "David", "Adjaye", "OM OBE RA", None, "Adjaye Associates", 714),
            ],
            tmp_path,
        )

        imp = import_index_excel(path, db_session)
        artists = db_session.query(IndexArtist).filter_by(import_id=imp.id).all()
        assert len(artists) == 1
        a = artists[0]
        assert a.is_ra_member is True
        assert a.title == "Sir"
        assert a.quals == "OM OBE RA"

        cat_nums = db_session.query(IndexCatNumber).filter_by(artist_id=a.id).all()
        assert len(cat_nums) == 1
        assert cat_nums[0].cat_no == 714
        assert cat_nums[0].courtesy == "Adjaye Associates"

    def test_company_detection(self, db_session, tmp_path):
        path = _make_workbook(
            [
                (None, None, "AKT II", None, None, None, "787;788"),
            ],
            tmp_path,
        )

        imp = import_index_excel(path, db_session)
        artists = db_session.query(IndexArtist).filter_by(import_id=imp.id).all()
        assert len(artists) == 1
        a = artists[0]
        assert a.is_company is True
        assert a.company == "AKT II"

        # Should have a validation warning
        warnings = (
            db_session.query(ValidationWarning)
            .filter_by(import_id=imp.id, warning_type="possible_company")
            .all()
        )
        assert len(warnings) == 1


class TestMerging:
    def test_merge_no_courtesy_duplicates(self, db_session, tmp_path):
        """Two rows for same artist with no courtesy → merged."""
        path = _make_workbook(
            [
                (None, "Tamara", "Kostianovsky", None, None, None, "1237"),
                (None, "Tamara", "Kostianovsky", None, None, None, "1234;1235;1236"),
            ],
            tmp_path,
        )

        imp = import_index_excel(path, db_session)
        artists = db_session.query(IndexArtist).filter_by(import_id=imp.id).all()
        assert len(artists) == 1

        cat_nums = (
            db_session.query(IndexCatNumber)
            .filter_by(artist_id=artists[0].id)
            .order_by(IndexCatNumber.cat_no)
            .all()
        )
        assert [c.cat_no for c in cat_nums] == [1234, 1235, 1236, 1237]
        assert all(c.courtesy is None for c in cat_nums)

    def test_keep_separate_courtesy(self, db_session, tmp_path):
        """Same artist with different courtesy lines → separate entries."""
        path = _make_workbook(
            [
                (
                    None,
                    "Cornelia",
                    "Parker",
                    "CBE RA",
                    None,
                    "Courtesy of Frith Street Gallery",
                    "1216;1238;1452",
                ),
                (
                    None,
                    "Cornelia",
                    "Parker",
                    "CBE RA",
                    None,
                    "Courtesy of Cristea Roberts Gallery",
                    "99;100;101;102",
                ),
            ],
            tmp_path,
        )

        imp = import_index_excel(path, db_session)
        artists = db_session.query(IndexArtist).filter_by(import_id=imp.id).all()
        assert len(artists) == 2
        assert all(a.is_ra_member is True for a in artists)

        # Each should have courtesy on their cat numbers
        for a in artists:
            cats = db_session.query(IndexCatNumber).filter_by(artist_id=a.id).all()
            assert all(c.courtesy is not None for c in cats)

    def test_mixed_courtesy_and_no_courtesy(self, db_session, tmp_path):
        """Same artist with some rows having courtesy and some not.
        E.g. Vanessa Jackson: one courtesy row + one plain row."""
        path = _make_workbook(
            [
                (
                    None,
                    "Vanessa",
                    "Jackson",
                    "RA",
                    None,
                    "Courtesy of Advanced Graphics London",
                    527,
                ),
                (None, "Vanessa", "Jackson", "RA", None, None, "458;545;848;1030"),
            ],
            tmp_path,
        )

        imp = import_index_excel(path, db_session)
        artists = db_session.query(IndexArtist).filter_by(import_id=imp.id).all()
        # Should be 2: one with courtesy, one without
        assert len(artists) == 2

        courtesy_artists = [
            a
            for a in artists
            if db_session.query(IndexCatNumber)
            .filter_by(artist_id=a.id)
            .first()
            .courtesy
            is not None
        ]
        plain_artists = [
            a
            for a in artists
            if db_session.query(IndexCatNumber)
            .filter_by(artist_id=a.id)
            .first()
            .courtesy
            is None
        ]
        assert len(courtesy_artists) == 1
        assert len(plain_artists) == 1


class TestSortKey:
    def test_sort_order(self, db_session, tmp_path):
        path = _make_workbook(
            [
                (None, "Cornelia", "Parker", "CBE RA", None, None, "381"),
                (None, "Roger", "Adams", None, None, None, "1266"),
                (None, "Marina", "Abramović", "HON RA", None, None, "1170"),
            ],
            tmp_path,
        )

        imp = import_index_excel(path, db_session)
        artists = (
            db_session.query(IndexArtist)
            .filter_by(import_id=imp.id)
            .order_by(IndexArtist.sort_key)
            .all()
        )
        names = [a.last_name for a in artists]
        assert names == ["Abramović", "Adams", "Parker"]


class TestMultiNameWarning:
    def test_and_in_name_emits_warning(self, db_session, tmp_path):
        path = _make_workbook(
            [
                (None, "Louisa", "Hutton and Sauerbach", None, None, None, "101"),
            ],
            tmp_path,
        )
        imp = import_index_excel(path, db_session)
        warnings = (
            db_session.query(ValidationWarning)
            .filter_by(import_id=imp.id, warning_type="multi_artist_name")
            .all()
        )
        assert len(warnings) == 1
        assert "multiple artists" in warnings[0].message.lower()

    def test_normal_name_no_warning(self, db_session, tmp_path):
        path = _make_workbook(
            [
                (None, "Roger", "Adams", None, None, None, "101"),
            ],
            tmp_path,
        )
        imp = import_index_excel(path, db_session)
        warnings = (
            db_session.query(ValidationWarning)
            .filter_by(import_id=imp.id, warning_type="multi_artist_name")
            .all()
        )
        assert len(warnings) == 0


class TestQualsInNameWarning:
    def test_obe_in_first_name_emits_warning(self, db_session, tmp_path):
        path = _make_workbook(
            [
                (None, "Louisa OBE", "Hutton", None, None, None, "101"),
            ],
            tmp_path,
        )
        imp = import_index_excel(path, db_session)
        warnings = (
            db_session.query(ValidationWarning)
            .filter_by(import_id=imp.id, warning_type="quals_in_name_field")
            .all()
        )
        assert len(warnings) == 1
        assert "OBE" in warnings[0].message

    def test_ra_in_last_name_emits_warning(self, db_session, tmp_path):
        path = _make_workbook(
            [
                (None, "Cornelia", "Parker RA", None, None, None, "205"),
            ],
            tmp_path,
        )
        imp = import_index_excel(path, db_session)
        warnings = (
            db_session.query(ValidationWarning)
            .filter_by(import_id=imp.id, warning_type="quals_in_name_field")
            .all()
        )
        assert len(warnings) == 1
        assert "RA" in warnings[0].message

    def test_normal_name_no_warning(self, db_session, tmp_path):
        path = _make_workbook(
            [
                (None, "Roger", "Adams", None, None, None, "101"),
            ],
            tmp_path,
        )
        imp = import_index_excel(path, db_session)
        warnings = (
            db_session.query(ValidationWarning)
            .filter_by(import_id=imp.id, warning_type="quals_in_name_field")
            .all()
        )
        assert len(warnings) == 0


class TestSingleNameArtist:
    def test_assemble(self, db_session, tmp_path):
        """Artist with only first name (Assemble) — treated as RA member."""
        path = _make_workbook(
            [
                (None, "Assemble", None, "RA", None, None, "607;705;721;779;780;1589"),
            ],
            tmp_path,
        )

        imp = import_index_excel(path, db_session)
        artists = db_session.query(IndexArtist).filter_by(import_id=imp.id).all()
        assert len(artists) == 1
        a = artists[0]
        assert a.first_name == "Assemble"
        assert a.last_name is None
        assert a.is_ra_member is True
        assert a.is_company is False
        assert a.sort_key == "assemble"

        cat_nums = (
            db_session.query(IndexCatNumber)
            .filter_by(artist_id=a.id)
            .order_by(IndexCatNumber.cat_no)
            .all()
        )
        assert len(cat_nums) == 6


class TestHeaderValidation:
    def test_missing_required_column(self, tmp_path):
        """Should raise IndexImportError if required columns are missing."""
        wb = Workbook()
        ws = wb.active
        ws.append(["Title", "First Name", "Quals"])
        ws.append([None, "Roger", None])
        path = str(tmp_path / "bad.xlsx")
        wb.save(path)

        with pytest.raises(IndexImportError, match="missing required column"):
            # No DB needed, should fail during header validation
            import_index_excel(path, None)

    def test_empty_spreadsheet_warning(self, db_session, tmp_path):
        path = _make_workbook([], tmp_path)
        imp = import_index_excel(path, db_session)
        warnings = (
            db_session.query(ValidationWarning)
            .filter_by(import_id=imp.id, warning_type="empty_spreadsheet")
            .all()
        )
        assert len(warnings) == 1


# ---------------------------------------------------------------------------
# Known artist lookup tests
# ---------------------------------------------------------------------------


class TestKnownArtistLookup:
    """Test that known_artists entries override heuristic normalisation."""

    def test_company_override(self, db_session, tmp_path):
        """Boyd & Evans: raw first='Boyd', raw last='& Evans' → company 'Boyd & Evans'."""
        # Seed the known artist entry
        db_session.add(
            KnownArtist(
                match_first_name="Boyd",
                match_last_name="& Evans",
                resolved_first_name="",  # empty string = clear field
                resolved_last_name="Boyd & Evans",
                resolved_is_company=True,
                notes="Partnership",
            )
        )
        db_session.commit()

        path = _make_workbook(
            [(None, "Boyd", "& Evans", None, None, None, "101;102")],
            tmp_path,
        )
        imp = import_index_excel(path, db_session)
        artists = db_session.query(IndexArtist).filter_by(import_id=imp.id).all()
        assert len(artists) == 1
        a = artists[0]
        assert a.last_name == "Boyd & Evans"
        assert a.first_name is None
        assert a.is_company is True
        # Sort key should use the resolved last name
        assert a.sort_key == "boyd & evans"

    def test_multi_artist_override(self, db_session, tmp_path):
        """Caruso/St John: raw last='Adam Caruso and Peter St John' → split."""
        db_session.add(
            KnownArtist(
                match_first_name=None,
                match_last_name="Adam Caruso and Peter St John",
                resolved_first_name="Adam",
                resolved_last_name="Caruso",
                resolved_second_artist="and Peter St John",
                notes="Full multi-artist name in Last Name column",
            )
        )
        db_session.commit()

        path = _make_workbook(
            [(None, None, "Adam Caruso and Peter St John", "RA", None, None, "501")],
            tmp_path,
        )
        imp = import_index_excel(path, db_session)
        artists = db_session.query(IndexArtist).filter_by(import_id=imp.id).all()
        assert len(artists) == 1
        a = artists[0]
        assert a.first_name == "Adam"
        assert a.last_name == "Caruso"
        assert a.second_artist == "and Peter St John"
        # Quals should be preserved from spreadsheet (not overridden)
        assert a.quals == "RA"
        assert a.is_ra_member is True
        assert a.sort_key == "caruso adam"

    def test_known_artist_emits_warning(self, db_session, tmp_path):
        """When a known artist match is used, it should emit a warning."""
        db_session.add(
            KnownArtist(
                match_first_name="Boyd",
                match_last_name="& Evans",
                resolved_last_name="Boyd & Evans",
                resolved_is_company=True,
                notes="Partnership",
            )
        )
        db_session.commit()

        path = _make_workbook(
            [(None, "Boyd", "& Evans", None, None, None, "101")],
            tmp_path,
        )
        imp = import_index_excel(path, db_session)
        warnings = (
            db_session.query(ValidationWarning)
            .filter_by(import_id=imp.id, warning_type="known_artist_applied")
            .all()
        )
        assert len(warnings) == 1
        assert "Partnership" in warnings[0].message

    def test_known_artist_suppresses_company_heuristic_warning(
        self, db_session, tmp_path
    ):
        """When a known artist sets is_company, the heuristic warning should NOT appear."""
        db_session.add(
            KnownArtist(
                match_first_name="Boyd",
                match_last_name="& Evans",
                resolved_first_name="",
                resolved_last_name="Boyd & Evans",
                resolved_is_company=True,
            )
        )
        db_session.commit()

        path = _make_workbook(
            [(None, "Boyd", "& Evans", None, None, None, "101")],
            tmp_path,
        )
        imp = import_index_excel(path, db_session)
        company_warnings = (
            db_session.query(ValidationWarning)
            .filter_by(import_id=imp.id, warning_type="possible_company")
            .all()
        )
        assert len(company_warnings) == 0

    def test_no_known_artist_match_uses_heuristics(self, db_session, tmp_path):
        """When there's no known artist match, standard heuristics apply."""
        # No known artists seeded
        path = _make_workbook(
            [(None, None, "AKT II", None, None, None, "787")],
            tmp_path,
        )
        imp = import_index_excel(path, db_session)
        artists = db_session.query(IndexArtist).filter_by(import_id=imp.id).all()
        assert len(artists) == 1
        assert artists[0].is_company is True
        assert artists[0].company == "AKT II"

    def test_case_insensitive_matching(self, db_session, tmp_path):
        """Known artist matching should be case-insensitive."""
        db_session.add(
            KnownArtist(
                match_first_name="boyd",
                match_last_name="& evans",
                resolved_last_name="Boyd & Evans",
                resolved_is_company=True,
            )
        )
        db_session.commit()

        path = _make_workbook(
            [(None, "Boyd", "& Evans", None, None, None, "101")],
            tmp_path,
        )
        imp = import_index_excel(path, db_session)
        artists = db_session.query(IndexArtist).filter_by(import_id=imp.id).all()
        assert len(artists) == 1
        assert artists[0].last_name == "Boyd & Evans"
        assert artists[0].is_company is True

    def test_plus_zatorski_as_company(self, db_session, tmp_path):
        """Zatorski + Zatorski: raw first='Zatorski', raw last='+ Zatorski' → company."""
        db_session.add(
            KnownArtist(
                match_first_name="Zatorski",
                match_last_name="+ Zatorski",
                resolved_first_name="",
                resolved_last_name="Zatorski + Zatorski",
                resolved_is_company=True,
                notes="Uses + instead of &",
            )
        )
        db_session.commit()

        path = _make_workbook(
            [(None, "Zatorski", "+ Zatorski", None, None, None, "555")],
            tmp_path,
        )
        imp = import_index_excel(path, db_session)
        artists = db_session.query(IndexArtist).filter_by(import_id=imp.id).all()
        assert len(artists) == 1
        a = artists[0]
        assert a.last_name == "Zatorski + Zatorski"
        assert a.first_name is None
        assert a.is_company is True
        assert a.sort_key == "zatorski + zatorski"
