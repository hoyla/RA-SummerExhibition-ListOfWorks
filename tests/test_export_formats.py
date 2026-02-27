"""
Tests for Phase 4 export formats: JSON, XML, CSV.
"""

import csv
import io
import json
import xml.etree.ElementTree as ET
from types import SimpleNamespace

from backend.app.services.export_renderer import (
    render_import_as_csv,
    render_import_as_json,
    render_import_as_xml,
    render_import_as_tagged_text,
)


# ---------------------------------------------------------------------------
# Shared test fixtures helpers
# ---------------------------------------------------------------------------


class FakeQuery:
    def __init__(self, results):
        self._results = results

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return self._results


class FakeSession:
    def __init__(self, sections, works, overrides=None):
        self.sections = sections
        self.works = works
        self.overrides = overrides or []

    def query(self, model):
        if model.__name__ == "Section":
            return FakeQuery(self.sections)
        if model.__name__ == "Work":
            return FakeQuery(self.works)
        if model.__name__ == "WorkOverride":
            return FakeQuery(self.overrides)
        return FakeQuery([])


def _section(name="Gallery 1", position=1, section_id="sec1"):
    return SimpleNamespace(
        id=section_id, import_id="imp1", name=name, position=position
    )


def _work(
    work_id="work1",
    number="1",
    artist="Test Artist",
    title="Test Title",
    price_numeric=1500,
    price_text="1500",
    edition_total=None,
    edition_price_numeric=None,
    honorifics=None,
    medium="Oil on canvas",
    section_id="sec1",
):
    return SimpleNamespace(
        id=work_id,
        raw_cat_no=number,
        artist_name=artist,
        artist_honorifics=honorifics,
        title=title,
        price_numeric=price_numeric,
        price_text=price_text,
        edition_total=edition_total,
        edition_price_numeric=edition_price_numeric,
        artwork=None,
        medium=medium,
        section_id=section_id,
        position_in_section=1,
        include_in_export=True,
    )


# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------


def test_json_export_valid_json():
    db = FakeSession([_section()], [_work()])
    output = render_import_as_json("imp1", db)
    parsed = json.loads(output)

    assert "sections" in parsed
    assert len(parsed["sections"]) == 1


def test_json_export_section_structure():
    db = FakeSession([_section(name="Main Gallery")], [_work()])
    parsed = json.loads(render_import_as_json("imp1", db))

    section = parsed["sections"][0]
    assert section["section_name"] == "Main Gallery"
    assert section["position"] == 1
    assert "works" in section


def test_json_export_work_fields():
    db = FakeSession(
        [_section()],
        [_work(number="42", artist="Jane Doe", title="Blue Sky", price_numeric=3000)],
    )
    parsed = json.loads(render_import_as_json("imp1", db))

    work = parsed["sections"][0]["works"][0]
    assert work["number"] == "42"
    assert work["artist"] == "Jane Doe"
    assert work["title"] == "Blue Sky"
    assert work["price_numeric"] == 3000


def test_json_export_multiple_sections():
    sections = [_section("Room A", 1, "sec1"), _section("Room B", 2, "sec2")]
    works = [
        _work("w1", section_id="sec1"),
        _work("w2", section_id="sec2"),
    ]
    db = FakeSession(sections, works)
    parsed = json.loads(render_import_as_json("imp1", db))

    assert len(parsed["sections"]) == 2
    assert parsed["sections"][0]["section_name"] == "Room A"
    assert parsed["sections"][1]["section_name"] == "Room B"


def test_json_export_edition_fields():
    db = FakeSession(
        [_section()],
        [_work(edition_total=6, edition_price_numeric=900)],
    )
    parsed = json.loads(render_import_as_json("imp1", db))
    work = parsed["sections"][0]["works"][0]

    assert work["edition_total"] == 6
    assert work["edition_price_numeric"] == 900


def test_json_export_unicode_preserved():
    db = FakeSession([_section()], [_work(artist="Liča Anić", title="Séquence")])
    output = render_import_as_json("imp1", db)

    assert "Liča Anić" in output
    assert "Séquence" in output


# ---------------------------------------------------------------------------
# XML export
# ---------------------------------------------------------------------------


def test_xml_export_valid_xml():
    db = FakeSession([_section()], [_work()])
    output = render_import_as_xml("imp1", db)

    root = ET.fromstring(output)
    assert root.tag == "catalogue"


def test_xml_export_section_attributes():
    db = FakeSession([_section(name="Print Room")], [_work()])
    root = ET.fromstring(render_import_as_xml("imp1", db))

    section = root.find("section")
    assert section is not None
    assert section.get("name") == "Print Room"
    assert section.get("position") == "1"


def test_xml_export_work_elements():
    db = FakeSession(
        [_section()],
        [_work(number="7", artist="Hockney", title="Pool")],
    )
    root = ET.fromstring(render_import_as_xml("imp1", db))

    work = root.find("section/work")
    assert work is not None
    assert work.find("number").text == "7"
    assert work.find("artist").text == "Hockney"
    assert work.find("title").text == "Pool"


def test_xml_export_null_fields_are_empty_elements():
    db = FakeSession([_section()], [_work(medium=None, honorifics=None)])
    root = ET.fromstring(render_import_as_xml("imp1", db))

    work = root.find("section/work")
    assert work.find("medium").text in (None, "")
    assert work.find("honorifics").text in (None, "")


def test_xml_export_multiple_works():
    works = [
        _work("w1", number="1", title="First"),
        _work("w2", number="2", title="Second"),
    ]
    # Give works different positions
    works[1].position_in_section = 2

    db = FakeSession([_section()], works)
    root = ET.fromstring(render_import_as_xml("imp1", db))

    found = root.findall("section/work")
    assert len(found) == 2
    titles = [w.find("title").text for w in found]
    assert "First" in titles
    assert "Second" in titles


def test_xml_export_unicode_preserved():
    db = FakeSession([_section()], [_work(artist="Liča Anić", title="Séquence")])
    output = render_import_as_xml("imp1", db)

    assert "Liča Anić" in output
    assert "Séquence" in output


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------


def _parse_csv(output: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(output))
    return list(reader)


def test_csv_export_has_header_row():
    db = FakeSession([_section()], [_work()])
    output = render_import_as_csv("imp1", db)

    assert output.startswith("section,number,artist,honorifics,title,")


def test_csv_export_correct_columns():
    db = FakeSession([_section()], [_work()])
    rows = _parse_csv(render_import_as_csv("imp1", db))

    row = rows[0]
    expected_keys = {
        "section",
        "number",
        "artist",
        "honorifics",
        "title",
        "price_numeric",
        "price_text",
        "edition_total",
        "edition_price_numeric",
        "artwork",
        "medium",
    }
    assert expected_keys == set(row.keys())


def test_csv_export_work_values():
    db = FakeSession(
        [_section(name="Gallery A")],
        [_work(number="3", artist="Smith", title="Red Work", price_numeric=2000)],
    )
    rows = _parse_csv(render_import_as_csv("imp1", db))

    row = rows[0]
    assert row["section"] == "Gallery A"
    assert row["number"] == "3"
    assert row["artist"] == "Smith"
    assert row["title"] == "Red Work"
    assert row["price_numeric"] == "2000"


def test_csv_export_empty_edition_fields_when_none():
    db = FakeSession(
        [_section()], [_work(edition_total=None, edition_price_numeric=None)]
    )
    rows = _parse_csv(render_import_as_csv("imp1", db))

    row = rows[0]
    assert row["edition_total"] == ""
    assert row["edition_price_numeric"] == ""


def test_csv_export_edition_values_when_present():
    db = FakeSession([_section()], [_work(edition_total=10, edition_price_numeric=750)])
    rows = _parse_csv(render_import_as_csv("imp1", db))

    row = rows[0]
    assert row["edition_total"] == "10"
    assert row["edition_price_numeric"] == "750"


def test_csv_export_multiple_works_produces_multiple_rows():
    works = [
        _work("w1", number="1", title="First"),
        _work("w2", number="2", title="Second"),
    ]
    db = FakeSession([_section()], works)
    rows = _parse_csv(render_import_as_csv("imp1", db))

    assert len(rows) == 2


def test_csv_export_section_column_repeated_per_work():
    works = [_work("w1", title="A"), _work("w2", title="B")]
    db = FakeSession([_section(name="The Gallery")], works)
    rows = _parse_csv(render_import_as_csv("imp1", db))

    assert all(r["section"] == "The Gallery" for r in rows)


def test_csv_export_unicode_preserved():
    db = FakeSession([_section()], [_work(artist="Liča Anić", title="Séquence")])
    output = render_import_as_csv("imp1", db)

    assert "Liča Anić" in output
    assert "Séquence" in output


# ---------------------------------------------------------------------------
# Consistency: all formats include same works
# ---------------------------------------------------------------------------


def test_all_formats_include_same_works():
    section = _section()
    works = [
        _work("w1", number="1", artist="Artist A", title="Work A"),
        _work("w2", number="2", artist="Artist B", title="Work B"),
    ]
    works[1].position_in_section = 2
    db1 = FakeSession([section], works)
    db2 = FakeSession([section], works)
    db3 = FakeSession([section], works)

    json_data = json.loads(render_import_as_json("imp1", db1))
    xml_root = ET.fromstring(render_import_as_xml("imp1", db2))
    csv_rows = _parse_csv(render_import_as_csv("imp1", db3))

    json_titles = [w["title"] for w in json_data["sections"][0]["works"]]
    xml_titles = [el.find("title").text for el in xml_root.findall("section/work")]
    csv_titles = [r["title"] for r in csv_rows]

    assert sorted(json_titles) == sorted(xml_titles) == sorted(csv_titles)


# ---------------------------------------------------------------------------
# Artwork field in all formats
# ---------------------------------------------------------------------------


def test_json_export_artwork_field():
    w = _work()
    w.artwork = 3
    db = FakeSession([_section()], [w])
    parsed = json.loads(render_import_as_json("imp1", db))
    assert parsed["sections"][0]["works"][0]["artwork"] == 3


def test_xml_export_artwork_element():
    w = _work()
    w.artwork = 5
    db = FakeSession([_section()], [w])
    root = ET.fromstring(render_import_as_xml("imp1", db))
    work = root.find("section/work")
    assert work.find("artwork").text == "5"


def test_xml_export_artwork_null():
    db = FakeSession([_section()], [_work()])
    root = ET.fromstring(render_import_as_xml("imp1", db))
    work = root.find("section/work")
    assert work.find("artwork").text in (None, "")


def test_csv_export_artwork_value():
    w = _work()
    w.artwork = 2
    db = FakeSession([_section()], [w])
    rows = _parse_csv(render_import_as_csv("imp1", db))
    assert rows[0]["artwork"] == "2"


def test_csv_export_artwork_empty_when_none():
    db = FakeSession([_section()], [_work()])
    rows = _parse_csv(render_import_as_csv("imp1", db))
    assert rows[0]["artwork"] == ""
