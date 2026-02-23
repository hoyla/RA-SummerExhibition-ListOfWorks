"""
Global normalisation config routes (honorific tokens).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
import hashlib
import json

from backend.app.api.deps import get_db
from backend.app.api.schemas import NormalisationIn
from backend.app.models.ruleset_model import Ruleset
from backend.app.services.normalisation_service import DEFAULT_HONORIFIC_TOKENS

router = APIRouter(tags=["config"])


def _get_normalisation_row(db: Session):
    """Return the global normalisation config row, or None."""
    return (
        db.query(Ruleset)
        .filter(Ruleset.config_type == "normalisation")
        .order_by(Ruleset.created_at.desc())
        .first()
    )


@router.get("/config")
def get_config(db: Session = Depends(get_db)):
    """Return global normalisation config (honorific tokens only)."""
    row = _get_normalisation_row(db)
    return {
        "honorific_tokens": (
            row.config.get("honorific_tokens", DEFAULT_HONORIFIC_TOKENS)
            if row
            else DEFAULT_HONORIFIC_TOKENS
        )
    }


@router.put("/config")
def put_config(body: NormalisationIn, db: Session = Depends(get_db)):
    """Save global normalisation config."""
    config_dict = {"honorific_tokens": body.honorific_tokens}
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
