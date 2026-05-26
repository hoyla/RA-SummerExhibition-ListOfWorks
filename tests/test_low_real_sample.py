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
from backend.app.services.low_tag_parser import parse_low_tags
from backend.app.services.low_diff import diff_low

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SAMPLES = os.path.join(_REPO, "test_sample_files")
_TXT = os.path.join(_SAMPLES, "Sample 26-05-26 with edition cstyle.txt")
_XLSX = os.path.join(_SAMPLES, "Catalogue List 2025_renamed.xlsx")
_SEED = os.path.join(_REPO, "backend", "seed_templates", "list-of-works-2026.json")

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
