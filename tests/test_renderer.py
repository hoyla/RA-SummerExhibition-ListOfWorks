from types import SimpleNamespace
from backend.app.services.export_renderer import (
    render_import_as_tagged_text,
    ExportConfig,
)


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


def test_renderer_price_and_edition_formatting():
    # Fake section
    section = SimpleNamespace(
        id="sec1",
        import_id="imp1",
        name="Test Section",
        position=1,
    )

    # Fake work
    work = SimpleNamespace(
        id="work1",
        raw_cat_no=1,
        artist_name="Test Artist",
        artist_honorifics=None,
        title="Test Title",
        price_numeric=3900,
        price_text="3900",
        edition_total=7,
        edition_price_numeric=920,
        artwork=None,
        medium=None,
        section_id="sec1",
        position_in_section=1,
        include_in_export=True,
    )

    fake_db = FakeSession([section], [work])

    output = render_import_as_tagged_text("imp1", fake_db)

    assert "£3,900" in output
    assert "(edition of 7 at £920)" in output
    assert ".00" not in output


def test_renderer_nfs_passes_through():
    section = SimpleNamespace(
        id="sec1",
        import_id="imp1",
        name="Test Section",
        position=1,
    )

    work = SimpleNamespace(
        id="work2",
        raw_cat_no=2,
        artist_name="Artist",
        artist_honorifics=None,
        title="Title",
        price_numeric=None,
        price_text="NFS",
        edition_total=None,
        edition_price_numeric=None,
        artwork=None,
        medium=None,
        section_id="sec1",
        position_in_section=1,
        include_in_export=True,
    )

    fake_db = FakeSession([section], [work])

    output = render_import_as_tagged_text("imp1", fake_db)

    assert "NFS" in output


def test_renderer_custom_config_changes_output():
    section = SimpleNamespace(
        id="sec1",
        import_id="imp1",
        name="Config Section",
        position=1,
    )

    work = SimpleNamespace(
        id="work3",
        raw_cat_no=3,
        artist_name="Artist",
        artist_honorifics=None,
        title="Title",
        price_numeric=1200,
        price_text="1200",
        edition_total=2,
        edition_price_numeric=500,
        artwork=None,
        medium=None,
        section_id="sec1",
        position_in_section=1,
        include_in_export=True,
    )

    fake_db = FakeSession([section], [work])

    custom_config = ExportConfig(
        currency_symbol="$",
        section_style="MySection",
        entry_style="MyEntry",
        edition_prefix="ed.",
    )

    output = render_import_as_tagged_text("imp1", fake_db, config=custom_config)

    assert "<ParaStyle:MySection>" in output
    assert "<ParaStyle:MyEntry>" in output
    assert "$1,200" in output
    assert "(ed. 2 at $500)" in output


def test_renderer_applies_override_values():
    section = SimpleNamespace(
        id="sec1",
        import_id="imp1",
        name="Override Section",
        position=1,
    )

    work = SimpleNamespace(
        id="work1",
        raw_cat_no=5,
        artist_name="Original Artist",
        title="Original Title",
        price_numeric=1000,
        price_text="1000",
        edition_total=None,
        edition_price_numeric=None,
        artwork=None,
        section_id="sec1",
        position_in_section=1,
        include_in_export=True,
        artist_honorifics=None,
        medium=None,
    )

    # Override changes artist and title
    override = SimpleNamespace(
        work_id="work1",
        title_override="Overridden Title",
        artist_name_override="Overridden Artist",
        artist_honorifics_override=None,
        price_numeric_override=None,
        price_text_override=None,
        edition_total_override=None,
        edition_price_numeric_override=None,
        medium_override=None,
    )

    fake_db = FakeSession([section], [work], overrides=[override])

    output = render_import_as_tagged_text("imp1", fake_db)

    assert "Overridden Title" in output
    assert "Overridden Artist" in output
    assert "Original Title" not in output
    assert "Original Artist" not in output
