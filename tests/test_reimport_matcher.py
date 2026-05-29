"""Unit tests for the pure re-import matcher.

The matcher is the safety net for the re-import flow: it decides which
preserved overrides get restored onto which new works, after a spreadsheet
re-upload. The motivating bug — silent misapplication of an override onto
a different work that happens to share a catalogue number after a renumber
— is pinned here by ``test_silent_misapplication_regression``.

These tests don't touch the DB, the API, or any I/O. They exercise the
``match_overrides`` function with hand-built ``OldWorkSnapshot`` /
``NewWorkRow`` lists so each behaviour is isolated.
"""

from backend.app.services.reimport_matcher import (
    NewWorkRow,
    OldWorkSnapshot,
    compute_fingerprint,
    match_overrides,
)

# ---------------------------------------------------------------------------
# Fingerprint normalisation
# ---------------------------------------------------------------------------


def test_fingerprint_is_case_and_whitespace_insensitive():
    a = compute_fingerprint("Cold Dark Matter", "Cornelia Parker", "Mixed Media")
    b = compute_fingerprint("  COLD  DARK MATTER  ", "cornelia parker", "  mixed media")
    assert a == b


def test_fingerprint_preserves_punctuation():
    """Punctuation is content, not noise — 'Untitled (after dusk)' and
    'Untitled after dusk' are different works and must not collide."""
    a = compute_fingerprint("Untitled (after dusk)", "X", "Y")
    b = compute_fingerprint("Untitled after dusk", "X", "Y")
    assert a != b


def test_fingerprint_handles_missing_fields():
    a = compute_fingerprint(None, "X", None)
    b = compute_fingerprint("", "X", "")
    assert a == b == ("", "x", "")


# ---------------------------------------------------------------------------
# Builders for tests
# ---------------------------------------------------------------------------


def _old(cat_no, title, artist, medium="oil", gallery="G1", *, override=None,
         include=True):
    return OldWorkSnapshot(
        cat_no=str(cat_no),
        gallery=gallery,
        fingerprint=compute_fingerprint(title, artist, medium),
        include_in_export=include,
        override=override,
        raw_title=title,
        raw_artist=artist,
    )


def _new(cat_no, title, artist, medium="oil", gallery="G1"):
    return NewWorkRow(
        cat_no=str(cat_no),
        gallery=gallery,
        fingerprint=compute_fingerprint(title, artist, medium),
        raw_title=title,
        raw_artist=artist,
    )


# ---------------------------------------------------------------------------
# Happy path: nothing has changed
# ---------------------------------------------------------------------------


def test_clean_reimport_all_cat_no_matches():
    old = [
        _old(1, "Sunset", "Jane", override={"price_numeric_override": 500}),
        _old(2, "Dawn", "John"),
        _old(3, "Noon", "Alice"),
    ]
    new = [
        _new(1, "Sunset", "Jane"),
        _new(2, "Dawn", "John"),
        _new(3, "Noon", "Alice"),
    ]
    plan = match_overrides(old, new)

    assert plan.matched_by_cat_no == 3
    assert plan.matched_by_fingerprint == 0
    assert plan.overrides_preserved == 1
    assert plan.overrides_at_risk == 0
    assert plan.added == 0
    assert plan.removed == 0
    assert plan.unmatched == []
    assert plan.ambiguous == []


# ---------------------------------------------------------------------------
# The motivating scenario: insertion + renumber
# ---------------------------------------------------------------------------


def test_insertion_shifts_cat_nos_fingerprint_recovers_overrides():
    """Gallery inserts a new work at position 2; everything from old 2
    onwards shifts +1. Override on old 3 must follow the content (now at
    cat 4), not the cat number (which is now a different work)."""
    old = [
        _old(1, "Sunset", "Jane"),
        _old(2, "Dawn", "John", override={"price_numeric_override": 1200}),
        _old(3, "Noon", "Alice", override={"medium_override": "watercolour"}),
    ]
    new = [
        _new(1, "Sunset", "Jane"),
        _new(2, "Brand New", "Bob"),   # inserted
        _new(3, "Dawn", "John"),       # was cat 2
        _new(4, "Noon", "Alice"),      # was cat 3
    ]
    plan = match_overrides(old, new)

    # All three old works are accounted for, two via fingerprint
    assert plan.matched_by_cat_no == 1   # only "Sunset" still at cat 1
    assert plan.matched_by_fingerprint == 2
    assert plan.overrides_preserved == 2  # both shifted overrides recovered
    assert plan.overrides_at_risk == 0
    assert plan.added == 1               # "Brand New"
    assert plan.removed == 0
    assert plan.unmatched == []
    assert plan.ambiguous == []

    # And specifically: the right overrides end up on the right new cat_nos
    by_old = {m.old_cat_no: m for m in plan.matched}
    assert by_old["2"].new_cat_no == "3"
    assert by_old["2"].via == "fingerprint"
    assert by_old["3"].new_cat_no == "4"
    assert by_old["3"].via == "fingerprint"


# ---------------------------------------------------------------------------
# The bug we're fixing — silent misapplication after a renumber
# ---------------------------------------------------------------------------


def test_silent_misapplication_regression():
    """Historical bug: when cat 2 in the new file is a *different work*
    from old cat 2 (because of an insertion), the old override should NOT
    be silently applied to it. With the matcher, the cat-no collision is
    detected and surfaced as ambiguous (or, when fingerprint recovers the
    real target elsewhere, simply matched there)."""
    old = [
        _old(1, "Sunset", "Jane"),
        _old(2, "Dawn", "John", override={"price_numeric_override": 9999,
                                          "title_override": "EXCLUSIVE"}),
    ]
    new = [
        _new(1, "Sunset", "Jane"),
        _new(2, "Brand New", "Bob"),   # different work at cat 2 — must not steal Dawn's override
    ]
    plan = match_overrides(old, new)

    # No matched item should pair Dawn's old cat 2 with the new "Brand New" work
    for m in plan.matched:
        if m.old_cat_no == "2":
            assert m.new_cat_no != "2" or m.via == "fingerprint", (
                "Old cat 2 override silently restored onto a different work — the bug"
            )
        # And vice versa: new cat 2 should not have inherited any override
        if m.new_cat_no == "2":
            assert m.old_cat_no != "2", (
                "New cat 2 (Brand New) inherited an override from old cat 2 (Dawn)"
            )

    # Dawn's override has no target in the new file, so it should be flagged
    assert plan.overrides_at_risk >= 1
    assert any(
        x.old_cat_no == "2" and x.reason == "cat_no_match_fingerprint_mismatch"
        for x in plan.ambiguous
    ), "Cat-no collision with content mismatch should be surfaced as ambiguous"


# ---------------------------------------------------------------------------
# Title edit on a renumbered work — fingerprint fails, override at risk
# ---------------------------------------------------------------------------


def test_title_edit_after_renumber_is_flagged_not_silently_lost():
    """A renumber AND a title correction on the same work: fingerprint
    can't find a target, so the override is reported as unmatched. The
    user can decide whether to re-apply it manually."""
    old = [
        _old(1, "Sunset", "Jane"),
        _old(2, "Untitled (after dust)", "John",
             override={"price_numeric_override": 1200}),
        _old(3, "Noon", "Alice"),
    ]
    new = [
        _new(1, "Sunset", "Jane"),
        _new(2, "Brand New", "Bob"),
        _new(3, "Untitled (after dusk)", "John"),  # title typo fixed AND renumbered
        _new(4, "Noon", "Alice"),
    ]
    plan = match_overrides(old, new)

    # Sunset and Noon match (cat-no and fingerprint respectively)
    assert plan.matched_by_cat_no == 1
    assert plan.matched_by_fingerprint == 1  # Noon (cat 3 → 4)

    # The Untitled-after-dust override should be reported as at-risk
    assert plan.overrides_at_risk == 1
    # Either unmatched or ambiguous (depending on whether the cat 2
    # collision wins) — but never silently matched.
    flagged_old_cat_nos = {x.old_cat_no for x in plan.unmatched} | {
        x.old_cat_no for x in plan.ambiguous
    }
    assert "2" in flagged_old_cat_nos


# ---------------------------------------------------------------------------
# Fingerprint collision (two new rows match one old)
# ---------------------------------------------------------------------------


def test_fingerprint_collision_is_ambiguous():
    """Two new works with identical (title, artist, medium) match one old
    override by fingerprint — refuse to guess which to attach it to."""
    old = [
        _old(99, "Untitled", "Anon", override={"notes": "x"}),
    ]
    new = [
        _new(101, "Untitled", "Anon"),
        _new(102, "Untitled", "Anon"),
    ]
    plan = match_overrides(old, new)
    assert plan.overrides_preserved == 0
    assert plan.overrides_at_risk == 1
    assert any(
        x.reason == "fingerprint_collision" and x.old_cat_no == "99"
        for x in plan.ambiguous
    )


# ---------------------------------------------------------------------------
# Removed works
# ---------------------------------------------------------------------------


def test_removed_work_reported_as_unmatched():
    old = [
        _old(1, "Sunset", "Jane"),
        _old(2, "Dawn", "John", override={"medium_override": "watercolour"}),
    ]
    new = [_new(1, "Sunset", "Jane")]
    plan = match_overrides(old, new)
    assert plan.removed == 1
    assert plan.unmatched and plan.unmatched[0].old_cat_no == "2"
    assert plan.overrides_at_risk == 1


# ---------------------------------------------------------------------------
# Gallery scope
# ---------------------------------------------------------------------------


def test_gallery_scope_excludes_out_of_scope_old_works():
    """Out-of-scope old works are not considered at risk by the matcher —
    the importer leaves them physically untouched."""
    old = [
        _old(1, "A", "X", gallery="G1", override={"price_numeric_override": 1}),
        _old(2, "B", "X", gallery="G1"),
        _old(3, "C", "X", gallery="G2", override={"price_numeric_override": 2}),
    ]
    # New file has rows for both galleries but we only re-import G2
    new = [
        _new(1, "A", "X", gallery="G1"),  # ignored (out of scope)
        _new(2, "B", "X", gallery="G1"),  # ignored
        _new(3, "C", "X", gallery="G2"),
    ]
    plan = match_overrides(old, new, gallery_scope={"G2"})

    # Only G2's work participates in matching
    assert plan.matched_by_cat_no == 1
    assert plan.overrides_preserved == 1
    assert plan.removed == 0  # G1 works are not "removed" — they're out of scope
    assert plan.added == 0


def test_gallery_scope_detects_cross_gallery_move():
    """A work whose fingerprint exists in a non-scope gallery shouldn't be
    silently duplicated into the selected gallery. The matcher warns."""
    old = [
        _old(1, "A", "X", gallery="G1"),     # out of scope
        _old(5, "Z", "Y", gallery="G2"),     # in scope
    ]
    new = [
        # A new row in G2 looks (by content) like the work currently in G1
        _new(5, "Z", "Y", gallery="G2"),
        _new(6, "A", "X", gallery="G2"),     # cross-gallery move into scope
    ]
    plan = match_overrides(old, new, gallery_scope={"G2"})

    assert plan.cross_gallery_warnings, "expected a cross-gallery move warning"
    w = plan.cross_gallery_warnings[0]
    assert w.new_cat_no == "6"
    assert w.old_cat_no == "1"
    assert w.old_gallery == "G1"
    assert w.new_gallery == "G2"


# ---------------------------------------------------------------------------
# Gallery summary
# ---------------------------------------------------------------------------


def test_gallery_summary_reports_cat_ranges_and_in_scope_flags():
    new = [
        _new(1, "A", "X", gallery="The Annenberg Courtyard"),
        _new(2, "B", "X", gallery="The Annenberg Courtyard"),
        _new(3, "C", "X", gallery="Gallery I"),
        _new(4, "D", "X", gallery="Gallery I"),
        _new(5, "E", "X", gallery="Gallery I"),
    ]
    plan = match_overrides([], new, gallery_scope={"Gallery I"})

    assert len(plan.galleries) == 2
    courtyard = plan.galleries[0]
    g1 = plan.galleries[1]

    assert courtyard.name == "The Annenberg Courtyard"
    assert courtyard.position == 1
    assert courtyard.work_count == 2
    assert courtyard.cat_no_min == 1
    assert courtyard.cat_no_max == 2
    assert courtyard.in_scope is False

    assert g1.name == "Gallery I"
    assert g1.position == 2
    assert g1.work_count == 3
    assert g1.cat_no_min == 3
    assert g1.cat_no_max == 5
    assert g1.in_scope is True


def test_gallery_summary_handles_non_numeric_cat_nos():
    new = [_new("A1", "x", "x", gallery="Foo")]
    plan = match_overrides([], new)
    assert plan.galleries[0].cat_no_min is None
    assert plan.galleries[0].cat_no_max is None
    assert plan.galleries[0].work_count == 1


# ---------------------------------------------------------------------------
# Empty / edge cases
# ---------------------------------------------------------------------------


def test_empty_inputs():
    plan = match_overrides([], [])
    assert plan.matched == []
    assert plan.unmatched == []
    assert plan.galleries == []
    assert plan.added == plan.removed == 0


def test_work_with_no_cat_no_falls_through_to_fingerprint():
    """Some imports might lack cat_nos on certain rows (header-only quirks).
    The matcher should still pair them via fingerprint when possible."""
    old = [_old("", "Sunset", "Jane", override={"notes": "x"})]
    new = [_new(1, "Sunset", "Jane")]
    plan = match_overrides(old, new)
    assert plan.matched_by_fingerprint == 1
    assert plan.overrides_preserved == 1
