"""Route-level tests for POST /imports/{id}/low-tag-diff (LOW → LPG
reconciliation, detection only). Exercises the full HTTP path: seed an import,
export real tags, post them back, and assert the diff."""

import uuid

from backend.app.models.import_model import Import
from backend.app.models.section_model import Section
from backend.app.models.work_model import Work


def _seed(db):
    imp = Import(filename="low.xlsx")
    db.add(imp)
    db.commit()
    db.refresh(imp)
    s1 = Section(import_id=imp.id, name="Gallery I", position=1)
    s2 = Section(import_id=imp.id, name="Gallery II", position=2)
    db.add_all([s1, s2])
    db.commit()
    db.refresh(s1)
    db.refresh(s2)
    db.add_all(
        [
            Work(import_id=imp.id, section_id=s1.id, position_in_section=1,
                 raw_cat_no="1", title="Sunset", artist_name="Jane Doe",
                 price_numeric=500, price_text="£500", medium="oil",
                 include_in_export=True),
            Work(import_id=imp.id, section_id=s1.id, position_in_section=2,
                 raw_cat_no="2", title="Moonrise", artist_name="John Roe",
                 price_numeric=750, price_text="", medium="acrylic",
                 include_in_export=True),
            Work(import_id=imp.id, section_id=s2.id, position_in_section=1,
                 raw_cat_no="3", title="Dawn", artist_name="Sam Poe",
                 price_text="NFS", medium="watercolour", include_in_export=True),
        ]
    )
    db.commit()
    return imp


def _post_tags(client, import_id, data: bytes, **params):
    return client.post(
        f"/imports/{import_id}/low-tag-diff",
        files={"file": ("low.txt", data, "text/plain")},
        params=params,
    )


def test_roundtrip_through_endpoint_no_findings(client, db_session):
    imp = _seed(db_session)
    tags = client.get(f"/imports/{imp.id}/export-tags").content
    r = _post_tags(client, imp.id, tags)
    assert r.status_code == 200
    body = r.json()
    assert body["parsed_entries"] == 3
    assert body["db_entries"] == 3
    assert body["warnings"] == []
    assert body["findings"] == []
    assert body["counts"]["matched"] == 3


def test_text_edit_through_endpoint(client, db_session):
    imp = _seed(db_session)
    tags = client.get(f"/imports/{imp.id}/export-tags").content
    modified = tags.replace(b"Sunset", b"Sunset Revisited")
    r = _post_tags(client, imp.id, modified)
    body = r.json()
    changes = [f for f in body["findings"] if f["kind"] == "field_change"]
    assert len(changes) == 1
    assert changes[0]["cat_no"] == "1"
    assert changes[0]["field"] == "title"
    assert changes[0]["low_value"] == "Sunset Revisited"
    assert changes[0]["fix_channel"] == "override"


def test_indesign_short_dialect_through_endpoint(client, db_session):
    imp = _seed(db_session)
    # A short-dialect (pstyle/cstyle, LF) file containing only cat 1.
    doc = (
        "<ASCII-MAC>\n<vsn:20.2>\n<dcs:CatNo=<Nextstyle:CatNo>>\n"
        "<pstyle:SectionTitle>Gallery I\n"
        "<pstyle:CatalogueEntry><cstyle:CatNo>1<cstyle:>\t"
        "<cstyle:ArtistName>Jane Doe<cstyle:>\t"
        "<cstyle:WorkTitle>Sunset<cstyle:>\t"
        "<cstyle:Price>£500<cstyle:>\t"
        "<cstyle:Medium>oil<cstyle:>\n"
    ).encode("mac_roman")
    r = _post_tags(client, imp.id, doc)
    assert r.status_code == 200
    body = r.json()
    assert body["parsed_entries"] == 1
    # cat 1 round-trips cleanly; cats 2 and 3 are absent from the file.
    removed = [f for f in body["findings"] if f["kind"] == "entry_removed"]
    assert {f["cat_no"] for f in removed} == {"2", "3"}
    assert not [f for f in body["findings"] if f["cat_no"] == "1"]


def test_unparseable_file_warns(client, db_session):
    imp = _seed(db_session)
    r = _post_tags(client, imp.id, b"this is not tagged text at all")
    assert r.status_code == 200
    body = r.json()
    assert body["parsed_entries"] == 0
    assert body["warnings"]  # loud warning, not a silent empty diff


def test_missing_import_returns_404(client):
    r = client.post(
        f"/imports/{uuid.uuid4()}/low-tag-diff",
        files={"file": ("low.txt", b"<ASCII-MAC>\r", "text/plain")},
    )
    assert r.status_code == 404
