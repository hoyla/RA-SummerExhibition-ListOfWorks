"""Validate seed template files are well-formed and use only recognised fields."""

import json
from pathlib import Path

import pytest

from backend.app.models.ruleset_model import Ruleset

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
            assert first or last, f"Entry {i} has neither match_first_name nor match_last_name"

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
            assert key not in seen, f"Duplicate match pattern at entries {seen[key]} and {i}: {key}"
            seen[key] = i


# ---------------------------------------------------------------------------
# Template seed validation (LoW, index, RA templates)
# ---------------------------------------------------------------------------


class TestTemplateSeedFiles:
    """Validate non-known-artist seed template JSON files."""

    @pytest.fixture(scope="class")
    def template_files(self):
        files = [f for f in sorted(SEED_DIR.glob("*.json")) if f.name != "known-artists.json"]
        assert len(files) > 0, "No template seed files found"
        return files

    def test_all_are_valid_json_objects(self, template_files):
        """Each template file must parse as a JSON object (dict)."""
        for f in template_files:
            with open(f, encoding="utf-8") as fp:
                data = json.load(fp)
            assert isinstance(data, dict), (
                f"{f.name} must be a JSON object, got {type(data).__name__}"
            )

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


def test_seed_templates_deletes_orphaned_builtins(db_session):
    """Templates marked is_builtin are deleted if no corresponding file exists."""
    from backend.app.services.seed_service import seed_builtin_templates as _seed_builtin_templates

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
    _seed_builtin_templates(db=db_session)

    # 4. Assert the orphaned built-in was deleted, but the user one was not
    assert not db_session.query(Ruleset).filter_by(slug="orphaned-template").one_or_none()
    assert db_session.query(Ruleset).filter_by(slug="user-template").one_or_none()


# ---------------------------------------------------------------------------
# Known-artists seed *loader* round-trip
# ---------------------------------------------------------------------------
#
# Complements the JSON-shape tests above: those verify the seed file is
# well-formed; the tests below verify the loader function (which reads the
# file and INSERTs rows) actually propagates every JSON field to the
# corresponding DB column.
#
# Motivation: we have shipped TWO bugs in this loader -- both the same
# root cause (column added to the model + API write paths, seed loader's
# KnownArtist(...) constructor forgotten):
#
#   1. is_seeded missing from the constructor -- every freshly seeded row
#      was wrongly labelled "user-defined" in the UI (Phase 19 regression).
#   2. resolved_title / resolved_company / resolved_address missing from
#      the constructor -- those values were silently dropped on every
#      fresh seed (Phase 20 regression).
#
# A NARROW test (just "is_seeded == True") would only catch #1. The
# structural round-trip test below catches both, AND any future variant
# of "human added a column to the model but forgot the seed loader".


def test_seed_known_artists_round_trip_propagates_all_fields(db_session):
    """Round-trip: every JSON entry => one DB row with all top-level fields preserved."""
    from backend.app.models.known_artist_model import KnownArtist
    from backend.app.services.seed_service import seed_known_artists as _seed_known_artists

    # Run the loader against the test's isolated in-memory DB
    _seed_known_artists(db=db_session)

    # Load the same JSON the loader read
    with open(SEED_DIR / "known-artists.json", encoding="utf-8") as fp:
        entries = json.load(fp)

    rows = db_session.query(KnownArtist).all()
    assert len(rows) == len(entries), (
        f"loader created {len(rows)} rows but JSON has {len(entries)} entries -- "
        "some entries are being dropped (or duplicated)"
    )

    # Match each JSON entry to its DB row by the (match_first, match_last, match_quals)
    # natural key.  Use this rather than insertion order to be robust against any
    # future reordering inside the loader.
    rows_by_key = {(r.match_first_name, r.match_last_name, r.match_quals): r for r in rows}

    # Every top-level JSON key that has a corresponding KnownArtist column
    # must be propagated faithfully.  This is the structural assertion that
    # would have failed under either of the two regressions above.
    for entry in entries:
        key = (
            entry.get("match_first_name"),
            entry.get("match_last_name"),
            entry.get("match_quals"),
        )
        assert key in rows_by_key, f"JSON entry {key!r} did not produce a DB row"
        row = rows_by_key[key]

        for field, expected in entry.items():
            assert hasattr(row, field), (
                f"JSON has unknown field {field!r} on entry {key!r} -- "
                f"either the schema validator above is stale, or the "
                f"model has lost a column"
            )
            actual = getattr(row, field)
            assert actual == expected, (
                f"entry {key!r}: field {field!r} not propagated to DB row "
                f"(json={expected!r}, db={actual!r})"
            )

        # is_seeded gets its own explicit assertion because it's not in the
        # JSON file -- it's a constant set by the loader to distinguish
        # "shipped with the app" from "added via the admin UI".
        assert row.is_seeded is True, (
            f"entry {key!r}: is_seeded must be True for loader-inserted rows, got {row.is_seeded!r}"
        )


def test_seed_known_artists_is_idempotent(db_session):
    """Running the loader twice does not duplicate rows."""
    from backend.app.models.known_artist_model import KnownArtist
    from backend.app.services.seed_service import seed_known_artists as _seed_known_artists

    _seed_known_artists(db=db_session)
    first_count = db_session.query(KnownArtist).count()

    _seed_known_artists(db=db_session)
    second_count = db_session.query(KnownArtist).count()

    assert first_count == second_count, (
        f"loader is not idempotent: first run {first_count} rows, "
        f"second run {second_count} rows (duplicate inserts)"
    )


# ---------------------------------------------------------------------------
# Known-artists loader: coexistence semantics
# ---------------------------------------------------------------------------
#
# Schema-level: known_artists has a unique constraint on
# (match_first_name, match_last_name, match_quals, is_seeded). The is_seeded
# discriminator in that constraint is deliberate -- it allows one seed row
# and one user-customised row to coexist for the same match key. The
# lookup code in build_known_artist_cache() then prefers user rows over
# seed rows at lookup time ("User entries take priority over seeded ones").
#
# The seed loader must respect both halves of this: when an editor has
# created a user override for a seed key, the loader should still insert
# the seed row alongside (so that deleting the user override later falls
# back to the seed value rather than to no-match).


def test_seed_known_artists_inserts_alongside_user_override(db_session):
    """If a user row exists for a seed key, the seed row is still inserted."""
    from backend.app.models.known_artist_model import KnownArtist
    from backend.app.services.seed_service import seed_known_artists

    # Pick a real seed entry to clash on
    with open(SEED_DIR / "known-artists.json", encoding="utf-8") as fp:
        entries = json.load(fp)
    target = entries[0]

    # Pre-create a user override with the same match key but a different
    # resolved value -- mimicking an editor who has customised this artist.
    user_row = KnownArtist(
        match_first_name=target.get("match_first_name"),
        match_last_name=target.get("match_last_name"),
        match_quals=target.get("match_quals"),
        resolved_first_name="USER_OVERRIDE",
        resolved_last_name="OVERRIDDEN",
        is_seeded=False,
    )
    db_session.add(user_row)
    db_session.commit()

    seed_known_artists(db=db_session)
    db_session.commit()

    matching = (
        db_session.query(KnownArtist)
        .filter(
            KnownArtist.match_first_name == target.get("match_first_name"),
            KnownArtist.match_last_name == target.get("match_last_name"),
            KnownArtist.match_quals == target.get("match_quals"),
        )
        .all()
    )

    # Both rows should now exist for this match key
    assert len(matching) == 2, (
        f"expected user row + seed row to coexist for match key, got {len(matching)}"
    )
    flags = sorted([r.is_seeded for r in matching])
    assert flags == [False, True], f"expected one user + one seed, got is_seeded={flags}"

    # User row's resolved value must be preserved -- the loader must not
    # touch existing rows
    user = next(r for r in matching if not r.is_seeded)
    assert user.resolved_first_name == "USER_OVERRIDE"
    assert user.resolved_last_name == "OVERRIDDEN"


def test_seed_known_artists_returns_added_skipped_counts(db_session):
    """Loader returns (added, skipped) tuple for caller bookkeeping."""
    from backend.app.services.seed_service import seed_known_artists

    with open(SEED_DIR / "known-artists.json", encoding="utf-8") as fp:
        entries = json.load(fp)

    added, skipped = seed_known_artists(db=db_session)
    assert added == len(entries), f"first run: expected all {len(entries)} inserted, got {added}"
    assert skipped == 0, f"first run: expected nothing skipped, got {skipped}"

    added2, skipped2 = seed_known_artists(db=db_session)
    assert added2 == 0, f"second run: expected nothing inserted, got {added2}"
    assert skipped2 == len(entries), (
        f"second run: expected all {len(entries)} skipped, got {skipped2}"
    )


# ---------------------------------------------------------------------------
# Built-in templates loader: structural round-trip
# ---------------------------------------------------------------------------
#
# Analogous to the known-artists round-trip test above: assert that every
# seed JSON file produces a Ruleset row with the expected slug/name/config
# values. Catches the same class of bug -- column added to Ruleset (or
# semantics changed in the JSON shape) but the loader's constructor or
# upsert path not updated.


def test_seed_builtin_templates_round_trip(db_session):
    """Every seed JSON file (excluding known-artists.json) produces one Ruleset row."""
    import hashlib

    from backend.app.services.seed_service import seed_builtin_templates

    seed_builtin_templates(db=db_session)

    seed_files = sorted(f for f in SEED_DIR.glob("*.json") if f.name != "known-artists.json")
    rulesets_by_slug = {r.slug: r for r in db_session.query(Ruleset).all()}

    assert len(rulesets_by_slug) == len(seed_files), (
        f"loader created {len(rulesets_by_slug)} rulesets from {len(seed_files)} seed files"
    )

    for seed_file in seed_files:
        slug = seed_file.stem
        assert slug in rulesets_by_slug, f"no Ruleset row inserted for seed file {seed_file.name}"
        row = rulesets_by_slug[slug]

        with open(seed_file, encoding="utf-8") as fp:
            raw = json.load(fp)
        expected_name = raw.pop("_name", slug)
        expected_config_type = raw.pop("_config_type", "template")
        expected_hash = hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()

        assert row.name == expected_name, f"{slug}: name mismatch"
        assert row.config_type == expected_config_type, f"{slug}: config_type mismatch"
        assert row.config == raw, f"{slug}: config payload mismatch"
        assert row.config_hash == expected_hash, f"{slug}: hash mismatch"
        assert row.is_builtin is True, f"{slug}: is_builtin must be True for loader-inserted rows"


def test_seed_builtin_templates_is_idempotent(db_session):
    """Running the loader twice does not duplicate rows."""
    from backend.app.services.seed_service import seed_builtin_templates

    seed_builtin_templates(db=db_session)
    first_count = db_session.query(Ruleset).count()

    seed_builtin_templates(db=db_session)
    second_count = db_session.query(Ruleset).count()

    assert first_count == second_count, (
        f"loader is not idempotent: first run {first_count}, second run {second_count}"
    )
