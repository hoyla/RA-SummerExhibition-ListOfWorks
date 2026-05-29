"""Real-data validation for the LOW → LPG reconciliation feature.

Parses the actual InDesign LOW export in ``test_sample_files/`` and diffs it
against the source spreadsheet it was produced from. This locks in the real
InDesign tag dialect (short ``<pstyle>``/``<cstyle>`` tags, LF breaks,
backslash-escaped style names, ``<0x####>`` escapes) and proves the pipeline
produces **no false positives** on a faithful (uncorrected) export of the real
2025 catalogue (1729 works).
"""

import json
import os
from types import SimpleNamespace

import pytest

from backend.app.api.low_exports import _ruleset_to_export_config
from backend.app.services.excel_importer import import_excel
from backend.app.services.export_renderer import _collect_export_data
from backend.app.services.low_diff import diff_low
from backend.app.services.low_tag_parser import parse_low_tags

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Git-tracked fixtures required by the test suite live here; the rest of
# test_sample_files/ is disposable/local-only working data.
_SAMPLES = os.path.join(
    _REPO, "test_sample_files", "tracked_samples_for_automated_tests"
)
_TXT = os.path.join(_SAMPLES, "Sample 26-05-26 with edition cstyle.txt")
_XLSX = os.path.join(_SAMPLES, "Catalogue List 2025_renamed.xlsx")
_SEED = os.path.join(_REPO, "backend", "seed_templates", "list-of-works-2026.json")
# A heavily hand-edited *final* InDesign LoW export: merged cat-no/title runs,
# inline <ccase:>/kerning tags, headings sharing lines with entries, "works N-NN"
# in gallery titles. Exercises the messy-real-file parsing path.
_FINAL = os.path.join(_SAMPLES, "LoW 2025 final with edition style 1.txt")

pytestmark = pytest.mark.skipif(
    not (os.path.exists(_TXT) and os.path.exists(_XLSX)),
    reason="real sample files not present",
)


def _config_2026():
    cfg = json.load(open(_SEED))
    cfg.pop("_name", None)
    return _ruleset_to_export_config(SimpleNamespace(config=cfg))


def _parse_real():
    with open(_TXT, encoding="mac_roman") as fh:
        return parse_low_tags(fh.read(), _config_2026())


def test_real_export_parses_all_entries_and_fields():
    parsed = _parse_real()
    assert len(parsed) == 1729

    by_cat = {e.cat_no: e for e in parsed}
    e = by_cat["8"]
    assert e.section_name == "Wohl Central Hall"
    assert e.fields["title"] == "PAST AND FUTURE"
    assert e.fields["artist"] == "Farshid Moussavi"
    assert e.fields["honorifics"] == "ra"  # lowercased per the 2026 template
    assert e.fields["price"] == "£1,200"  # <0x00A3>1,200 decoded
    assert e.fields["medium"] == "print on paper"
    assert e.fields["edition"] == "(edition of 7 at £920)"

    # A smart apostrophe (exported as <0x2019>) decodes correctly.
    assert by_cat["10"].fields["title"] == "LET’S TALK TO THE DEAD"


def test_real_export_diffs_clean_against_source(db_session):
    config = _config_2026()
    imp = import_excel(
        _XLSX, db_session, display_name="Catalogue List 2025_renamed.xlsx"
    )
    collected = _collect_export_data(imp.id, db_session)
    result = diff_low(_parse_real(), collected, config)

    # The export is a faithful (uncorrected) render of the spreadsheet, so the
    # diff must be empty — only cosmetic round-trip differences, all suppressed.
    assert result.counts["matched"] == 1729
    assert result.counts["db_only"] == 0
    assert result.counts["low_only"] == 0
    assert result.findings == []


@pytest.mark.skipif(not os.path.exists(_FINAL), reason="final LoW sample not present")
def test_final_low_export_parses_cleanly():
    """The messy final export must parse: clean cat numbers (not merged with
    titles), inline formatting tags stripped from values, clean gallery names."""
    with open(_FINAL, encoding="mac_roman") as fh:
        parsed = parse_low_tags(fh.read(), _config_2026())

    assert len(parsed) == 1729  # every work, including the tricky ones
    by_cat = {e.cat_no: e for e in parsed}
    assert "1" in by_cat  # cat 1 was previously lost (heading shared its line)
    # 405-412 carry a local leading override (<cl:…>) inside the cat-no run;
    # inline tags must be stripped before the tab-split or they're dropped.
    assert all(str(n) in by_cat for n in range(405, 413))
    # Cat numbers are clean digits, not "2\tHOW MUCH IS A LOT?".
    assert all(e.cat_no.isdigit() for e in parsed[:100])
    # Roman-numeral galleries ("Gallery Roman") are recognised as sections too,
    # with the "works N-NN." annotation (incl. its trailing dot) stripped out.
    sections = {e.section_name for e in parsed}
    assert "IX" in sections and "VIII" in sections
    assert not any(s.endswith(".") or "works " in s.lower() for s in sections)
    # Inline <ccase:>/<cs:>/kerning tags are stripped from field values.
    blob = " ".join(v for e in parsed for v in e.fields.values())
    assert "<ccase" not in blob and "<cstyle" not in blob and "<cs:" not in blob
    # Gallery names are clean — no residual tags or "works N-NN" range.
    assert all("<" not in (e.section_name or "") for e in parsed)
    assert all("works " not in (e.section_name or "").lower() for e in parsed)
