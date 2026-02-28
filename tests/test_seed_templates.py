"""Validate seed template files are well-formed and use only recognised fields."""

import json
from pathlib import Path

import pytest

SEED_DIR = Path(__file__).resolve().parent.parent / "backend" / "seed_templates"

# ---------------------------------------------------------------------------
# Known-artists seed validation
# ---------------------------------------------------------------------------

KNOWN_ARTIST_VALID_FIELDS = {
    # Match fields
    "match_first_name",
    "match_last_name",
    "match_quals",
    # Resolved artist 1
    "resolved_first_name",
    "resolved_last_name",
    "resolved_quals",
    "resolved_title",
    "resolved_is_company",
    "resolved_company",
    "resolved_address",
    # Resolved artist 2
    "resolved_artist2_first_name",
    "resolved_artist2_last_name",
    "resolved_artist2_quals",
    # Resolved artist 3
    "resolved_artist3_first_name",
    "resolved_artist3_last_name",
    "resolved_artist3_quals",
    # RA styling flags
    "resolved_artist1_ra_styled",
    "resolved_artist2_ra_styled",
    "resolved_artist3_ra_styled",
    # Metadata
    "notes",
}

KNOWN_ARTIST_TEXT_FIELDS = KNOWN_ARTIST_VALID_FIELDS - {
    "resolved_is_company",
    "resolved_artist1_ra_styled",
    "resolved_artist2_ra_styled",
    "resolved_artist3_ra_styled",
}

KNOWN_ARTIST_BOOL_FIELDS = {
    "resolved_is_company",
    "resolved_artist1_ra_styled",
    "resolved_artist2_ra_styled",
    "resolved_artist3_ra_styled",
}


class TestKnownArtistsSeed:
    """Validate backend/seed_templates/known-artists.json."""

    @pytest.fixture(scope="class")
    def entries(self):
        path = SEED_DIR / "known-artists.json"
        assert path.exists(), f"Seed file not found: {path}"
        with open(path, encoding="utf-8") as fp:
            data = json.load(fp)
        assert isinstance(data, list), "known-artists.json must be a JSON array"
        assert len(data) > 0, "known-artists.json must not be empty"
        return data

    def test_is_valid_json_array(self, entries):
        """File parses as a non-empty JSON array."""
        assert isinstance(entries, list)
        assert len(entries) > 0

    def test_no_unrecognised_fields(self, entries):
        """Every entry uses only fields that exist on the KnownArtist model."""
        for i, entry in enumerate(entries):
            unknown = set(entry.keys()) - KNOWN_ARTIST_VALID_FIELDS
            assert not unknown, (
                f"Entry {i} has unrecognised field(s): {unknown}  "
                f"(match: {entry.get('match_first_name')} {entry.get('match_last_name')})"
            )

    def test_has_at_least_one_match_field(self, entries):
        """Every entry must have at least match_first_name or match_last_name."""
        for i, entry in enumerate(entries):
            first = entry.get("match_first_name")
            last = entry.get("match_last_name")
            assert (
                first or last
            ), f"Entry {i} has neither match_first_name nor match_last_name"

    def test_text_fields_are_strings_or_null(self, entries):
        """Text fields must be str or None, never int/bool/list."""
        for i, entry in enumerate(entries):
            for key in KNOWN_ARTIST_TEXT_FIELDS:
                if key not in entry:
                    continue
                val = entry[key]
                assert val is None or isinstance(val, str), (
                    f"Entry {i} field '{key}' should be str or null, got {type(val).__name__}: {val!r}  "
                    f"(match: {entry.get('match_first_name')} {entry.get('match_last_name')})"
                )

    def test_bool_fields_are_bools_or_null(self, entries):
        """Boolean fields must be bool or None."""
        for i, entry in enumerate(entries):
            for key in KNOWN_ARTIST_BOOL_FIELDS:
                if key not in entry:
                    continue
                val = entry[key]
                assert val is None or isinstance(val, bool), (
                    f"Entry {i} field '{key}' should be bool or null, got {type(val).__name__}: {val!r}  "
                    f"(match: {entry.get('match_first_name')} {entry.get('match_last_name')})"
                )

    def test_no_duplicate_match_patterns(self, entries):
        """No two entries should have the same (first, last, quals) triple."""
        seen = {}
        for i, entry in enumerate(entries):
            key = (
                (entry.get("match_first_name") or "").strip().lower(),
                (entry.get("match_last_name") or "").strip().lower(),
                (entry.get("match_quals") or "").strip().lower(),
            )
            assert (
                key not in seen
            ), f"Duplicate match pattern at entries {seen[key]} and {i}: {key}"
            seen[key] = i


# ---------------------------------------------------------------------------
# Template seed validation (LoW, index, RA templates)
# ---------------------------------------------------------------------------


class TestTemplateSeedFiles:
    """Validate non-known-artist seed template JSON files."""

    @pytest.fixture(scope="class")
    def template_files(self):
        files = [
            f for f in sorted(SEED_DIR.glob("*.json")) if f.name != "known-artists.json"
        ]
        assert len(files) > 0, "No template seed files found"
        return files

    def test_all_are_valid_json_objects(self, template_files):
        """Each template file must parse as a JSON object (dict)."""
        for f in template_files:
            with open(f, encoding="utf-8") as fp:
                data = json.load(fp)
            assert isinstance(
                data, dict
            ), f"{f.name} must be a JSON object, got {type(data).__name__}"

    def test_all_have_name(self, template_files):
        """Each template file must have a _name field."""
        for f in template_files:
            with open(f, encoding="utf-8") as fp:
                data = json.load(fp)
            assert "_name" in data, f"{f.name} is missing '_name' field"
            assert isinstance(data["_name"], str), f"{f.name} '_name' must be a string"
            assert data["_name"].strip(), f"{f.name} '_name' must not be empty"

    def test_index_templates_have_config_type(self, template_files):
        """Index template files must declare _config_type = 'index_template'."""
        for f in template_files:
            with open(f, encoding="utf-8") as fp:
                data = json.load(fp)
            if "index" in f.stem:
                assert data.get("_config_type") == "index_template", (
                    f"{f.name} looks like an index template but _config_type is "
                    f"{data.get('_config_type')!r}, expected 'index_template'"
                )

    def test_style_values_are_strings(self, template_files):
        """Style fields must be strings (not int, bool, list, etc.)."""
        for f in template_files:
            with open(f, encoding="utf-8") as fp:
                data = json.load(fp)
            for key, val in data.items():
                if key.startswith("_"):
                    continue
                if key.endswith("_style") and val is not None:
                    assert isinstance(val, str), (
                        f"{f.name} field '{key}' should be a string, "
                        f"got {type(val).__name__}: {val!r}"
                    )


# ---------------------------------------------------------------------------
# Template seeding process
# ---------------------------------------------------------------------------

from backend.app.models.ruleset_model import Ruleset


def test_seed_templates_deletes_orphaned_builtins(db_session):
    """Templates marked is_builtin are deleted if no corresponding file exists."""
    from backend.app.main import _seed_builtin_templates
    # 1. Create an orphaned built-in template that has no corresponding file
    db_session.add(
        Ruleset(
            name="Orphaned Template",
            slug="orphaned-template",
            is_builtin=True,
            config_type="template",
            config={"some": "config"},
            config_hash="dummy_hash",
        )
    )
    # 2. Create a non-builtin template that should NOT be deleted
    db_session.add(
        Ruleset(
            name="User Template",
            slug="user-template",
            is_builtin=False,
            config_type="template",
            config={"some": "config"},
            config_hash="dummy_hash",
        )
    )
    db_session.commit()

    assert db_session.query(Ruleset).filter_by(slug="orphaned-template").one_or_none()
    assert db_session.query(Ruleset).filter_by(slug="user-template").one_or_none()

    # 3. Run the seeding process
    _seed_builtin_templates()

    # 4. Assert the orphaned built-in was deleted, but the user one was not
    assert not db_session.query(Ruleset).filter_by(slug="orphaned-template").one_or_none()
    assert db_session.query(Ruleset).filter_by(slug="user-template").one_or_none()
