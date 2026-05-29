"""LPG (Large Print Guide) rendering.

The LPG is the same List of Works data in a different layout: each element in
its own paragraph style, rather than character styles separated by tabs/soft
returns within one paragraph. It is driven by the *same* template/config model
as the LOW — a template simply gives some components a ``paragraph_style``.

These tests prove the paragraphed render path produces the structure seen in the
real export (a small tracked excerpt lives under
``test_sample_files/tracked_samples_for_automated_tests/``):

    <pstyle:LPGTITLE>{n}\t{title}
    <pstyle:LPGARTIST>{artist}[ <cstyle:LPGSMALLCAPS>{hon}<cstyle:>]
    <pstyle:LPGMEDIUM>{medium}
    <pstyle:LPGEDITION>(edition of N at £Y)      # only when present
    <pstyle:LPGPRICE>{price}

(We emit the long-form <ParaStyle:>/<CharStyle:> dialect; InDesign reads both.)
"""

import json
import re
from pathlib import Path
from types import SimpleNamespace

from backend.app.api.low_exports import _ruleset_to_export_config
from backend.app.models.import_model import Import
from backend.app.models.section_model import Section
from backend.app.models.work_model import Work
from backend.app.services.export_renderer import (
    escape_for_mac_roman,
    render_import_as_tagged_text,
)

_REPO = Path(__file__).resolve().parent.parent
_SEED = _REPO / "backend" / "seed_templates" / "large-print-guide-2026.json"
# A small, git-tracked excerpt of the real export (the full file is too large to
# commit). Covers both per-work paragraph-style shapes (with / without edition).
_SAMPLE = (
    _REPO / "test_sample_files" / "tracked_samples_for_automated_tests" / "lpg_sample_small.txt"
)


def _lpg_config():
    cfg = json.loads(_SEED.read_text(encoding="utf-8"))
    cfg.pop("_name", None)
    return _ruleset_to_export_config(SimpleNamespace(config=cfg))


def _seed(db):
    imp = Import(filename="lpg.xlsx", product_type="list_of_works")
    db.add(imp)
    db.commit()
    db.refresh(imp)
    sec = Section(import_id=imp.id, name="Gallery I", position=1)
    db.add(sec)
    db.commit()
    db.refresh(sec)
    db.add_all(
        [
            # plain, NFS, no edition
            Work(
                import_id=imp.id,
                section_id=sec.id,
                position_in_section=1,
                raw_cat_no="1",
                title="The Meddling Fiend",
                title_cased="The Meddling Fiend",
                artist_name="Nicola Turner",
                medium="mixed media",
                price_text="NFS",
                include_in_export=True,
            ),
            # priced, with an edition
            Work(
                import_id=imp.id,
                section_id=sec.id,
                position_in_section=2,
                raw_cat_no="3",
                title="Superhero Rabbit",
                title_cased="Superhero Rabbit",
                artist_name="Joanna Ham",
                medium="screenprint with UV neon ink",
                price_numeric=140,
                price_text="140",
                edition_total=200,
                edition_price_numeric=90,
                include_in_export=True,
            ),
            # honorifics (small caps), priced
            Work(
                import_id=imp.id,
                section_id=sec.id,
                position_in_section=3,
                raw_cat_no="5",
                title="Centre-Fold",
                title_cased="Centre-Fold",
                artist_name="John Carter",
                artist_honorifics="RA",
                medium="acrylic with marble powder on plywood",
                price_numeric=7500,
                price_text="7500",
                include_in_export=True,
            ),
        ]
    )
    db.commit()
    return imp


def test_lpg_render_matches_sample_structure(db_session):
    imp = _seed(db_session)
    out = render_import_as_tagged_text(imp.id, db_session, _lpg_config())

    # No gallery heading paragraph (blank section_style → per-room files).
    assert "Gallery I" not in out
    assert "<ParaStyle:LPGTITLE>" not in out.split("\r")[0]  # header line is just <ASCII-MAC>

    # Work 1: number+title share the LPGTITLE paragraph, tab-separated; NFS price;
    # no edition paragraph.
    assert "<ParaStyle:LPGTITLE>1\tThe Meddling Fiend\r" in out
    assert "<ParaStyle:LPGARTIST>Nicola Turner\r" in out
    assert "<ParaStyle:LPGMEDIUM>mixed media\r" in out
    assert "<ParaStyle:LPGPRICE>NFS\r" in out

    # Work 3: conditional edition paragraph present, bracketed, "edition of" prefix.
    assert "<ParaStyle:LPGEDITION>(edition of 200 at £90)\r" in out
    assert "<ParaStyle:LPGPRICE>£140\r" in out

    # Work 5: honorifics as an inline small-caps run, lowercased to match the LPG.
    assert "<ParaStyle:LPGARTIST>John Carter <CharStyle:LPGSMALLCAPS>ra<CharStyle:>\r" in out


def test_lpg_title_cased_falls_back_to_title_when_absent(db_session):
    """Legacy data with no title_cased must not render a blank title — it falls
    back to the plain title."""
    imp = Import(filename="legacy.xlsx", product_type="list_of_works")
    db_session.add(imp)
    db_session.commit()
    db_session.refresh(imp)
    sec = Section(import_id=imp.id, name="Gallery I", position=1)
    db_session.add(sec)
    db_session.commit()
    db_session.refresh(sec)
    db_session.add(
        Work(
            import_id=imp.id,
            section_id=sec.id,
            position_in_section=1,
            raw_cat_no="1",
            title="LEGACY ALL CAPS",
            title_cased=None,
            artist_name="Someone",
            medium="oil",
            price_text="NFS",
            include_in_export=True,
        )
    )
    db_session.commit()
    out = render_import_as_tagged_text(imp.id, db_session, _lpg_config())
    assert "<ParaStyle:LPGTITLE>1\tLEGACY ALL CAPS\r" in out


def test_lpg_edition_paragraph_omitted_when_absent(db_session):
    imp = _seed(db_session)
    out = render_import_as_tagged_text(imp.id, db_session, _lpg_config())
    # Only one of the three works has an edition.
    assert out.count("<ParaStyle:LPGEDITION>") == 1


def test_lpg_pound_is_mac_roman_safe(db_session):
    imp = _seed(db_session)
    rendered = render_import_as_tagged_text(imp.id, db_session, _lpg_config())
    out = escape_for_mac_roman(rendered)
    # £ is encodable in Mac Roman, so it stays literal (the sample's <0x00A3> is
    # InDesign's equivalent choice — both decode to £). The key guarantee is that
    # the escaped output round-trips through mac_roman without error.
    assert "£140" in out
    out.encode("mac_roman")  # must not raise


def test_low_template_still_renders_inline(db_session):
    """The paragraphed path must not affect ordinary LOW templates: with no
    component carrying a paragraph_style, everything stays in one entry paragraph."""
    imp = _seed(db_session)
    from backend.app.services.export_renderer import DEFAULT_CONFIG

    out = render_import_as_tagged_text(imp.id, db_session, DEFAULT_CONFIG)
    # One CatalogueEntry paragraph per work; no LPG paragraph styles.
    assert "<ParaStyle:CatalogueEntry>" in out
    assert "LPGARTIST" not in out


def _seed_lpg_template(db):
    import hashlib

    from backend.app.models.ruleset_model import Ruleset

    cfg = json.loads(_SEED.read_text(encoding="utf-8"))
    cfg.pop("_name", None)
    rs = Ruleset(
        name="Large Print Guide 2026",
        config=cfg,
        config_hash=hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest(),
        config_type="template",
        is_builtin=False,
        slug="lpg-test",
    )
    db.add(rs)
    db.commit()
    db.refresh(rs)
    return rs


def test_section_export_filename_embeds_template_and_gallery(client, db_session):
    imp = _seed(db_session)
    sec = db_session.query(Section).filter(Section.import_id == imp.id).first()
    rs = _seed_lpg_template(db_session)
    r = client.get(f"/imports/{imp.id}/sections/{sec.id}/export-tags?template_id={rs.id}")
    assert r.status_code == 200
    cd = r.headers.get("content-disposition", "")
    assert "Large-Print-Guide-2026" in cd
    assert "Gallery-I" in cd  # the room, so per-gallery files are distinguishable


def test_full_export_filename_uses_template_name(client, db_session):
    imp = _seed(db_session)
    rs = _seed_lpg_template(db_session)
    r = client.get(f"/imports/{imp.id}/export-tags?template_id={rs.id}")
    cd = r.headers.get("content-disposition", "")
    assert 'filename="Large-Print-Guide-2026.txt"' in cd


def test_full_export_filename_falls_back_without_template(client, db_session):
    imp = _seed(db_session)
    r = client.get(f"/imports/{imp.id}/export-tags")
    cd = r.headers.get("content-disposition", "")
    assert 'filename="catalogue.txt"' in cd


def test_lpg_paragraph_style_sequence_matches_real_sample():
    """Tie the structure to the real export: the per-work paragraph-style sequence
    our template produces (TITLE, ARTIST, MEDIUM, [EDITION], PRICE) is exactly the
    sequence found in the sample file."""
    text = _SAMPLE.read_text(encoding="mac_roman")
    styles = re.findall(r"<pstyle:(LPG[A-Z]+)>", text)

    # Walk the sample as records starting at each LPGTITLE; collect the style run.
    records = []
    current = []
    for s in styles:
        if s == "LPGTITLE" and current:
            records.append(current)
            current = []
        current.append(s)
    if current:
        records.append(current)

    seen = {tuple(r) for r in records}
    # The sample only ever uses these two shapes (with/without an edition line).
    assert ("LPGTITLE", "LPGARTIST", "LPGMEDIUM", "LPGPRICE") in seen
    assert ("LPGTITLE", "LPGARTIST", "LPGMEDIUM", "LPGEDITION", "LPGPRICE") in seen
    assert seen <= {
        ("LPGTITLE", "LPGARTIST", "LPGMEDIUM", "LPGPRICE"),
        ("LPGTITLE", "LPGARTIST", "LPGMEDIUM", "LPGEDITION", "LPGPRICE"),
    }
