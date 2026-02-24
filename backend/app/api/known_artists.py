"""
API routes for managing the known artists lookup table.
"""

import json
import logging
import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.api.auth import require_role
from backend.app.api.deps import get_db
from backend.app.api.schemas import KnownArtistOut, KnownArtistCreate, KnownArtistUpdate
from backend.app.models.known_artist_model import KnownArtist

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/known-artists", tags=["known-artists"])


# ---------------------------------------------------------------------------
# List all
# ---------------------------------------------------------------------------


@router.get("", response_model=List[KnownArtistOut])
def list_known_artists(db: Session = Depends(get_db)):
    """Return all known artist lookup entries."""
    rows = db.query(KnownArtist).order_by(KnownArtist.match_last_name).all()
    return [
        KnownArtistOut(
            id=str(r.id),
            match_first_name=r.match_first_name,
            match_last_name=r.match_last_name,
            resolved_first_name=r.resolved_first_name,
            resolved_last_name=r.resolved_last_name,
            resolved_quals=r.resolved_quals,
            resolved_second_artist=r.resolved_second_artist,
            resolved_is_company=r.resolved_is_company,
            notes=r.notes,
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=KnownArtistOut,
    status_code=201,
    dependencies=[Depends(require_role("editor"))],
)
def create_known_artist(
    body: KnownArtistCreate,
    db: Session = Depends(get_db),
):
    """Add a new known artist entry."""
    ka = KnownArtist(
        match_first_name=body.match_first_name,
        match_last_name=body.match_last_name,
        resolved_first_name=body.resolved_first_name,
        resolved_last_name=body.resolved_last_name,
        resolved_quals=body.resolved_quals,
        resolved_second_artist=body.resolved_second_artist,
        resolved_is_company=body.resolved_is_company,
        notes=body.notes,
    )
    db.add(ka)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A known artist entry with the same match fields already exists.",
        )
    db.refresh(ka)
    return KnownArtistOut(
        id=str(ka.id),
        match_first_name=ka.match_first_name,
        match_last_name=ka.match_last_name,
        resolved_first_name=ka.resolved_first_name,
        resolved_last_name=ka.resolved_last_name,
        resolved_quals=ka.resolved_quals,
        resolved_second_artist=ka.resolved_second_artist,
        resolved_is_company=ka.resolved_is_company,
        notes=ka.notes,
    )


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


@router.patch(
    "/{known_artist_id}",
    response_model=KnownArtistOut,
    dependencies=[Depends(require_role("editor"))],
)
def update_known_artist(
    known_artist_id: str,
    body: KnownArtistUpdate,
    db: Session = Depends(get_db),
):
    """Update an existing known artist entry."""
    ka = (
        db.query(KnownArtist)
        .filter(KnownArtist.id == uuid.UUID(known_artist_id))
        .first()
    )
    if not ka:
        raise HTTPException(status_code=404, detail="Known artist not found")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(ka, field, value)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A known artist entry with the same match fields already exists.",
        )
    db.refresh(ka)
    return KnownArtistOut(
        id=str(ka.id),
        match_first_name=ka.match_first_name,
        match_last_name=ka.match_last_name,
        resolved_first_name=ka.resolved_first_name,
        resolved_last_name=ka.resolved_last_name,
        resolved_quals=ka.resolved_quals,
        resolved_second_artist=ka.resolved_second_artist,
        resolved_is_company=ka.resolved_is_company,
        notes=ka.notes,
    )


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


@router.delete(
    "/{known_artist_id}",
    status_code=204,
    dependencies=[Depends(require_role("editor"))],
)
def delete_known_artist(
    known_artist_id: str,
    db: Session = Depends(get_db),
):
    """Remove a known artist entry."""
    ka = (
        db.query(KnownArtist)
        .filter(KnownArtist.id == uuid.UUID(known_artist_id))
        .first()
    )
    if not ka:
        raise HTTPException(status_code=404, detail="Known artist not found")
    db.delete(ka)
    db.commit()


# ---------------------------------------------------------------------------
# Seed from JSON
# ---------------------------------------------------------------------------


@router.post(
    "/seed", response_model=dict, dependencies=[Depends(require_role("admin"))]
)
def seed_known_artists(db: Session = Depends(get_db)):
    """Load known artists from the seed file (known-artists.json).

    Skips entries whose match fields already exist.
    Returns a count of added/skipped entries.
    """
    seed_path = (
        Path(__file__).resolve().parent.parent.parent
        / "seed_templates"
        / "known-artists.json"
    )
    if not seed_path.exists():
        raise HTTPException(status_code=404, detail="Seed file not found")

    with open(seed_path, encoding="utf-8") as fp:
        entries = json.load(fp)

    added = 0
    skipped = 0
    for entry in entries:
        match_first = entry.get("match_first_name")
        match_last = entry.get("match_last_name")

        existing = (
            db.query(KnownArtist)
            .filter(
                KnownArtist.match_first_name == match_first,
                KnownArtist.match_last_name == match_last,
            )
            .first()
        )
        if existing:
            skipped += 1
            continue

        ka = KnownArtist(
            match_first_name=match_first,
            match_last_name=match_last,
            resolved_first_name=entry.get("resolved_first_name"),
            resolved_last_name=entry.get("resolved_last_name"),
            resolved_quals=entry.get("resolved_quals"),
            resolved_second_artist=entry.get("resolved_second_artist"),
            resolved_is_company=entry.get("resolved_is_company"),
            notes=entry.get("notes"),
        )
        db.add(ka)
        added += 1

    db.commit()
    return {"added": added, "skipped": skipped, "total": added + skipped}
