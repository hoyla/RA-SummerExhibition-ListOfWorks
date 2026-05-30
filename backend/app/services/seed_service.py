"""Startup seeding: upserts built-in templates and known-artists from JSON files."""

import hashlib
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_SEED_DIR = Path(__file__).resolve().parent.parent.parent.parent / "backend" / "seed_templates"


def seed_builtin_templates(db=None) -> None:
    """Upsert built-in templates from seed JSON files and delete orphaned ones.

    If *db* is provided (e.g. in tests) the caller owns the session – this
    function will flush but not commit/rollback/close it.  When *db* is None
    a new SessionLocal session is created, committed, and closed here.
    """
    from backend.app.db import SessionLocal as _SessionLocal
    from backend.app.models.ruleset_model import Ruleset as _Ruleset

    if not _SEED_DIR.exists():
        return

    _external_db = db is not None
    if not _external_db:
        db = _SessionLocal()
    try:
        seed_files = [f for f in _SEED_DIR.glob("*.json") if f.name != "known-artists.json"]
        seed_slugs = {f.stem for f in seed_files}

        for f in sorted(seed_files):
            slug = f.stem
            with open(f, encoding="utf-8") as fp:
                seed = json.load(fp)
            name = seed.pop("_name", slug)
            config_type = seed.pop("_config_type", "template")
            cfg_hash = hashlib.sha256(json.dumps(seed, sort_keys=True).encode()).hexdigest()
            existing = db.query(_Ruleset).filter(_Ruleset.slug == slug).first()
            if existing:
                if existing.name != name:
                    existing.name = name
                if existing.config_type != config_type:
                    existing.config_type = config_type
                if existing.config_hash != cfg_hash:
                    existing.config = seed
                    existing.config_hash = cfg_hash
                continue
            db.add(
                _Ruleset(
                    name=name,
                    config=seed,
                    config_hash=cfg_hash,
                    config_type=config_type,
                    is_builtin=True,
                    slug=slug,
                )
            )

        # Delete built-in templates that no longer have a corresponding file
        db_slugs = {
            row[0] for row in db.query(_Ruleset.slug).filter(_Ruleset.is_builtin == True).all()
        }
        deleted_slugs = db_slugs - seed_slugs
        if deleted_slugs:
            db.query(_Ruleset).filter(
                _Ruleset.is_builtin == True, _Ruleset.slug.in_(deleted_slugs)
            ).delete(synchronize_session=False)
            logger.info("Deleted orphaned seed templates: %s", ", ".join(sorted(deleted_slugs)))

        if not _external_db:
            db.commit()
        else:
            db.flush()
    except Exception as exc:  # pragma: no cover
        logger.error("Seed error: %s", exc)
        if not _external_db:
            db.rollback()
    finally:
        if not _external_db:
            db.close()


def seed_known_artists(db=None) -> tuple[int, int]:
    """Idempotently insert KnownArtist rows from known-artists.json.

    Dedupe key matches the schema's uniqueness constraint exactly:
    ``(match_first_name, match_last_name, match_quals, is_seeded=True)``.
    A seed row is skipped only if a prior **seed** row with the same match
    key already exists; a user-created row (is_seeded=False) with the same
    match key does NOT block re-insertion. This is intentional and aligns
    with two existing pieces of design:

      * The unique constraint is declared as
        ``(match_first_name, match_last_name, match_quals, is_seeded)`` --
        i.e. the schema explicitly allows one seed row and one user row
        per match key to coexist.
      * The match-cache builder in ``index_override_service.build_known_artist_cache``
        explicitly handles coexistence at lookup time, with the comment
        "User entries (is_seeded=False) take priority over seeded ones."

    Net behaviour: if an editor has customised an artist by creating a
    user override, the seed row may also exist (recreated on every startup
    if the editor or a manual SQL action ever deleted it). At lookup time
    the user override always wins. If the editor later removes their
    override via the DELETE endpoint, the seed row is still present and
    lookups fall back to the seed value rather than to no-match -- the
    cleanest possible revert path.

    Returns:
        ``(added, skipped)`` -- counts of rows inserted and rows skipped
        because a matching seed row already existed.

    If *db* is provided (e.g. in tests, or by the admin re-seed endpoint
    that wants to share its request-scoped session) the caller owns the
    session: this function will flush but not commit/rollback/close.
    When *db* is None a new SessionLocal session is created, committed,
    and closed here.
    """
    from backend.app.models.known_artist_model import KnownArtist as _KnownArtist

    seed_file = _SEED_DIR / "known-artists.json"
    if not seed_file.exists():
        return (0, 0)

    from backend.app.db import SessionLocal as _SessionLocal

    _external_db = db is not None
    if not _external_db:
        db = _SessionLocal()
    added = 0
    skipped = 0
    try:
        with open(seed_file, encoding="utf-8") as fp:
            entries = json.load(fp)

        for entry in entries:
            match_first = entry.get("match_first_name")
            match_last = entry.get("match_last_name")
            existing = (
                db.query(_KnownArtist)
                .filter(
                    _KnownArtist.match_first_name == match_first,
                    _KnownArtist.match_last_name == match_last,
                    _KnownArtist.match_quals == entry.get("match_quals"),
                    _KnownArtist.is_seeded == True,  # noqa: E712 -- SQLAlchemy filter, see ruff_lint_baseline.md
                )
                .first()
            )
            if existing:
                skipped += 1
                continue
            db.add(
                _KnownArtist(
                    match_first_name=match_first,
                    match_last_name=match_last,
                    match_quals=entry.get("match_quals"),
                    resolved_first_name=entry.get("resolved_first_name"),
                    resolved_last_name=entry.get("resolved_last_name"),
                    resolved_quals=entry.get("resolved_quals"),
                    resolved_title=entry.get("resolved_title"),
                    resolved_is_company=entry.get("resolved_is_company"),
                    resolved_company=entry.get("resolved_company"),
                    resolved_address=entry.get("resolved_address"),
                    resolved_artist2_first_name=entry.get("resolved_artist2_first_name"),
                    resolved_artist2_last_name=entry.get("resolved_artist2_last_name"),
                    resolved_artist2_quals=entry.get("resolved_artist2_quals"),
                    resolved_artist3_first_name=entry.get("resolved_artist3_first_name"),
                    resolved_artist3_last_name=entry.get("resolved_artist3_last_name"),
                    resolved_artist3_quals=entry.get("resolved_artist3_quals"),
                    resolved_artist1_ra_styled=entry.get("resolved_artist1_ra_styled"),
                    resolved_artist2_ra_styled=entry.get("resolved_artist2_ra_styled"),
                    resolved_artist3_ra_styled=entry.get("resolved_artist3_ra_styled"),
                    resolved_artist2_shared_surname=entry.get("resolved_artist2_shared_surname"),
                    resolved_artist3_shared_surname=entry.get("resolved_artist3_shared_surname"),
                    notes=entry.get("notes"),
                    is_seeded=True,
                )
            )
            added += 1
        if added:
            logger.info("Seeded %d known artist(s)", added)
        if not _external_db:
            db.commit()
        else:
            db.flush()
        return (added, skipped)
    except Exception as exc:  # pragma: no cover
        logger.error("Known artists seed error: %s", exc)
        if not _external_db:
            db.rollback()
        return (added, skipped)
    finally:
        if not _external_db:
            db.close()
