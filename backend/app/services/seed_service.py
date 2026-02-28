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
            cfg_hash = hashlib.sha256(
                json.dumps(seed, sort_keys=True).encode()
            ).hexdigest()
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
            row[0]
            for row in db.query(_Ruleset.slug).filter(_Ruleset.is_builtin == True).all()
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
