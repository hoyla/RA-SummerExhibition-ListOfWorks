"""
Global normalisation config routes (honorific tokens).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
import hashlib
import json

from backend.app.api.auth import require_role
from backend.app.api.deps import get_db
from backend.app.api.schemas import NormalisationIn
from backend.app.models.ruleset_model import Ruleset
from backend.app.services.normalisation_service import (
    DEFAULT_EDITION_SUPPRESS_MAX,
    DEFAULT_HONORIFIC_TOKENS,
    DEFAULT_TEXT_SUBSTITUTIONS,
    DEFAULT_TITLE_CASE_EXCEPTIONS,
)

router = APIRouter(tags=["config"])


def _get_normalisation_row(db: Session):
    """Return the global normalisation config row, or None."""
    return (
        db.query(Ruleset)
        .filter(Ruleset.config_type == "normalisation")
        .order_by(Ruleset.created_at.desc())
        .first()
    )


def load_normalisation_settings(db: Session) -> dict:
    """Resolve the effective normalisation settings (saved config or shipped
    defaults). Single source of truth for *both* GET /config and the import
    pipeline, so what an admin saves is exactly what an import applies."""
    row = _get_normalisation_row(db)
    cfg = row.config if row else {}
    return {
        "honorific_tokens": cfg.get("honorific_tokens", DEFAULT_HONORIFIC_TOKENS),
        "edition_suppress_max": cfg.get(
            "edition_suppress_max", DEFAULT_EDITION_SUPPRESS_MAX
        ),
        "text_substitutions": cfg.get(
            "text_substitutions", DEFAULT_TEXT_SUBSTITUTIONS
        ),
        "title_case_exceptions": cfg.get(
            "title_case_exceptions", DEFAULT_TITLE_CASE_EXCEPTIONS
        ),
    }


@router.get("/config")
def get_config(db: Session = Depends(get_db)):
    """Return the effective global normalisation config."""
    return load_normalisation_settings(db)


@router.put("/config", dependencies=[Depends(require_role("admin"))])
def put_config(body: NormalisationIn, db: Session = Depends(get_db)):
    """Save the global normalisation config (full replace)."""
    config_dict = {
        "honorific_tokens": body.honorific_tokens,
        "edition_suppress_max": body.edition_suppress_max,
        "text_substitutions": [s.model_dump() for s in body.text_substitutions],
        "title_case_exceptions": body.title_case_exceptions,
    }
    config_hash = hashlib.sha256(
        json.dumps(config_dict, sort_keys=True).encode()
    ).hexdigest()
    row = _get_normalisation_row(db)
    if row:
        row.config = config_dict
        row.config_hash = config_hash
    else:
        row = Ruleset(
            name="global_normalisation",
            config=config_dict,
            config_hash=config_hash,
            config_type="normalisation",
            is_builtin=False,
        )
        db.add(row)
    db.commit()
    return config_dict
