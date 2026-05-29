"""Route-level tests for POST /imports/{id}/low-tag-diff (LOW → LPG
reconciliation, detection only). Exercises the full HTTP path: seed an import,
export real tags, post them back, and assert the diff."""

import uuid

from backend.app.models.import_model import Import
from backend.app.models.override_model import WorkOverride
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


# --- persisted snapshots -------------------------------------------------------


def _post_snapshot(client, import_id, data: bytes, **params):
    return client.post(
        f"/imports/{import_id}/low-tag-snapshots",
        files={"file": ("low.txt", data, "text/plain")},
        params=params,
    )


def test_create_snapshot_persists_and_returns_diff(client, db_session):
    imp = _seed(db_session)
    tags = client.get(f"/imports/{imp.id}/export-tags").content
    r = _post_snapshot(client, imp.id, tags)
    assert r.status_code == 200
    body = r.json()
    assert body["snapshot"]["id"]
    assert body["snapshot"]["chars"] > 0
    assert body["diff"]["counts"]["matched"] == 3
    assert body["diff"]["findings"] == []
    # It is persisted.
    listing = client.get(f"/imports/{imp.id}/low-tag-snapshots").json()
    assert len(listing) == 1
    assert listing[0]["id"] == body["snapshot"]["id"]


def test_get_snapshot_recomputes_diff(client, db_session):
    imp = _seed(db_session)
    tags = client.get(f"/imports/{imp.id}/export-tags").content
    sid = _post_snapshot(client, imp.id, tags).json()["snapshot"]["id"]
    r = client.get(f"/imports/{imp.id}/low-tag-snapshots/{sid}")
    assert r.status_code == 200
    assert r.json()["diff"]["findings"] == []


def test_workflow_a_override_resolves_finding(client, db_session):
    """Persist a corrected file, see the diff, apply a matching override, then
    re-view: the resolved disparity disappears (the Workflow A loop)."""
    imp = _seed(db_session)
    tags = client.get(f"/imports/{imp.id}/export-tags").content
    modified = tags.replace(b"Sunset", b"Sunset Revised")  # edit cat 1 title

    body = _post_snapshot(client, imp.id, modified).json()
    sid = body["snapshot"]["id"]
    assert any(
        f["cat_no"] == "1" and f["field"] == "title"
        for f in body["diff"]["findings"]
    )

    # Apply the correction as an override on the matching work.
    work = db_session.query(Work).filter(Work.raw_cat_no == "1").first()
    db_session.add(WorkOverride(work_id=work.id, title_override="Sunset Revised"))
    db_session.commit()

    # Re-view the same stored snapshot — diff recomputes against current data.
    after = client.get(f"/imports/{imp.id}/low-tag-snapshots/{sid}").json()
    assert not [
        f for f in after["diff"]["findings"]
        if f["cat_no"] == "1" and f["field"] == "title"
    ]


def test_delete_snapshot(client, db_session):
    imp = _seed(db_session)
    tags = client.get(f"/imports/{imp.id}/export-tags").content
    sid = _post_snapshot(client, imp.id, tags).json()["snapshot"]["id"]
    assert client.delete(f"/imports/{imp.id}/low-tag-snapshots/{sid}").status_code == 200
    assert client.get(f"/imports/{imp.id}/low-tag-snapshots").json() == []
    assert client.get(f"/imports/{imp.id}/low-tag-snapshots/{sid}").status_code == 404


def test_reconcile_config_endpoint(client):
    """The reconciliation policy is exposed read-only for the Settings page."""
    r = client.get("/reconcile-config")
    assert r.status_code == 200
    cfg = r.json()
    assert cfg["severity"]["entry_added"] == "high"
    assert cfg["severity"]["field_change_default"] == "medium"
    assert cfg["fix_channel"]["field_change"] == "override"
    assert cfg["fix_channel"]["room_move"] == "spreadsheet"
    assert cfg["suppress_cosmetic"] is True
