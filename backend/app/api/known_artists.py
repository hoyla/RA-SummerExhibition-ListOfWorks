"""
API routes for managing the known artists lookup table.
"""

import json
import logging
import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.app.api.auth import require_role
from backend.app.api.deps import get_db
from backend.app.api.schemas import KnownArtistOut, KnownArtistCreate, KnownArtistUpdate
from backend.app.models.known_artist_model import KnownArtist

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/known-artists", tags=["known-artists"])


def _to_out(ka: KnownArtist) -> KnownArtistOut:
    """Map a KnownArtist row to its API output schema."""
    return KnownArtistOut(
        id=str(ka.id),
        match_first_name=ka.match_first_name,
        match_last_name=ka.match_last_name,
        match_quals=ka.match_quals,
        resolved_first_name=ka.resolved_first_name,
        resolved_last_name=ka.resolved_last_name,
        resolved_title=ka.resolved_title,
        resolved_quals=ka.resolved_quals,
        resolved_is_company=ka.resolved_is_company,
        resolved_company=ka.resolved_company,
        resolved_address=ka.resolved_address,
        resolved_artist2_first_name=ka.resolved_artist2_first_name,
        resolved_artist2_last_name=ka.resolved_artist2_last_name,
        resolved_artist2_quals=ka.resolved_artist2_quals,
        resolved_artist3_first_name=ka.resolved_artist3_first_name,
        resolved_artist3_last_name=ka.resolved_artist3_last_name,
        resolved_artist3_quals=ka.resolved_artist3_quals,
        resolved_artist1_ra_styled=ka.resolved_artist1_ra_styled,
        resolved_artist2_ra_styled=ka.resolved_artist2_ra_styled,
        resolved_artist3_ra_styled=ka.resolved_artist3_ra_styled,
        resolved_artist2_shared_surname=ka.resolved_artist2_shared_surname,
        resolved_artist3_shared_surname=ka.resolved_artist3_shared_surname,
        notes=ka.notes,
        is_seeded=ka.is_seeded,
    )


# ---------------------------------------------------------------------------
# List all
# ---------------------------------------------------------------------------


@router.get("", response_model=List[KnownArtistOut])
def list_known_artists(db: Session = Depends(get_db)):
    """Return all known artist lookup entries."""
    rows = (
        db.query(KnownArtist)
        .order_by(KnownArtist.match_last_name, KnownArtist.match_first_name)
        .all()
    )
    return [_to_out(r) for r in rows]


# ---------------------------------------------------------------------------
# Export as seed-format JSON
# ---------------------------------------------------------------------------

_SEED_FIELDS = [
    "match_first_name",
    "match_last_name",
    "match_quals",
    "resolved_first_name",
    "resolved_last_name",
    "resolved_title",
    "resolved_quals",
    "resolved_is_company",
    "resolved_company",
    "resolved_address",
    "resolved_artist2_first_name",
    "resolved_artist2_last_name",
    "resolved_artist2_quals",
    "resolved_artist3_first_name",
    "resolved_artist3_last_name",
    "resolved_artist3_quals",
    "resolved_artist1_ra_styled",
    "resolved_artist2_ra_styled",
    "resolved_artist3_ra_styled",
    "resolved_artist2_shared_surname",
    "resolved_artist3_shared_surname",
    "notes",
]


@router.get(
    "/export",
    dependencies=[Depends(require_role("admin"))],
)
def export_known_artists(db: Session = Depends(get_db)):
    """Export all known artists as a seed-format JSON file.

    Returns a downloadable JSON array that can be saved as
    ``seed_templates/known-artists.json`` for future deployments.
    Only includes fields that have a non-null value, matching the
    compact style used in the existing seed file.
    Entries are sorted alphabetically by last name then first name.
    """
    rows = (
        db.query(KnownArtist)
        .order_by(KnownArtist.match_last_name, KnownArtist.match_first_name)
        .all()
    )
    entries = []
    for ka in rows:
        entry = {}
        for field in _SEED_FIELDS:
            val = getattr(ka, field)
            if val is not None:
                entry[field] = val
        entries.append(entry)

    body = json.dumps(entries, indent=2, ensure_ascii=False) + "\n"
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Content-Disposition": 'attachment; filename="known-artists.json"',
        },
    )


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
        match_quals=body.match_quals,
        resolved_first_name=body.resolved_first_name,
        resolved_last_name=body.resolved_last_name,
        resolved_title=body.resolved_title,
        resolved_quals=body.resolved_quals,
        resolved_is_company=body.resolved_is_company,
        resolved_company=body.resolved_company,
        resolved_address=body.resolved_address,
        resolved_artist2_first_name=body.resolved_artist2_first_name,
        resolved_artist2_last_name=body.resolved_artist2_last_name,
        resolved_artist2_quals=body.resolved_artist2_quals,
        resolved_artist3_first_name=body.resolved_artist3_first_name,
        resolved_artist3_last_name=body.resolved_artist3_last_name,
        resolved_artist3_quals=body.resolved_artist3_quals,
        resolved_artist1_ra_styled=body.resolved_artist1_ra_styled,
        resolved_artist2_ra_styled=body.resolved_artist2_ra_styled,
        resolved_artist3_ra_styled=body.resolved_artist3_ra_styled,
        resolved_artist2_shared_surname=body.resolved_artist2_shared_surname,
        resolved_artist3_shared_surname=body.resolved_artist3_shared_surname,
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
    return _to_out(ka)


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
    if ka.is_seeded:
        raise HTTPException(
            status_code=403,
            detail="Built-in entries cannot be edited. Duplicate to create an editable copy.",
        )

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
    return _to_out(ka)


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
    if ka.is_seeded:
        raise HTTPException(
            status_code=403,
            detail="Built-in entries cannot be deleted.",
        )
    db.delete(ka)
    db.commit()


# ---------------------------------------------------------------------------
# Duplicate (create editable copy of a seeded entry)
# ---------------------------------------------------------------------------


@router.post(
    "/{known_artist_id}/duplicate",
    response_model=KnownArtistOut,
    status_code=201,
    dependencies=[Depends(require_role("editor"))],
)
def duplicate_known_artist(
    known_artist_id: str,
    db: Session = Depends(get_db),
):
    """Create an editable (non-seeded) copy of a known artist entry.

    Typically used to customise a built-in (seeded) entry while
    preserving the original.  The copy has ``is_seeded=False`` and can
    be freely edited or deleted.
    """
    source = (
        db.query(KnownArtist)
        .filter(KnownArtist.id == uuid.UUID(known_artist_id))
        .first()
    )
    if not source:
        raise HTTPException(status_code=404, detail="Known artist not found")

    # Check a user copy with the same match fields doesn't already exist
    existing_user_copy = (
        db.query(KnownArtist)
        .filter(
            KnownArtist.match_first_name == source.match_first_name,
            KnownArtist.match_last_name == source.match_last_name,
            KnownArtist.match_quals == source.match_quals,
            KnownArtist.is_seeded == False,  # noqa: E712
        )
        .first()
    )
    if existing_user_copy:
        raise HTTPException(
            status_code=409,
            detail="An editable copy of this entry already exists.",
        )

    copy = KnownArtist(
        match_first_name=source.match_first_name,
        match_last_name=source.match_last_name,
        match_quals=source.match_quals,
        resolved_first_name=source.resolved_first_name,
        resolved_last_name=source.resolved_last_name,
        resolved_title=source.resolved_title,
        resolved_quals=source.resolved_quals,
        resolved_is_company=source.resolved_is_company,
        resolved_company=source.resolved_company,
        resolved_address=source.resolved_address,
        resolved_artist2_first_name=source.resolved_artist2_first_name,
        resolved_artist2_last_name=source.resolved_artist2_last_name,
        resolved_artist2_quals=source.resolved_artist2_quals,
        resolved_artist3_first_name=source.resolved_artist3_first_name,
        resolved_artist3_last_name=source.resolved_artist3_last_name,
        resolved_artist3_quals=source.resolved_artist3_quals,
        resolved_artist1_ra_styled=source.resolved_artist1_ra_styled,
        resolved_artist2_ra_styled=source.resolved_artist2_ra_styled,
        resolved_artist3_ra_styled=source.resolved_artist3_ra_styled,
        notes=source.notes,
        is_seeded=False,
    )
    db.add(copy)
    db.commit()
    db.refresh(copy)
    return _to_out(copy)


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
                KnownArtist.match_quals == entry.get("match_quals"),
                KnownArtist.is_seeded == True,  # noqa: E712
            )
            .first()
        )
        if existing:
            skipped += 1
            continue

        ka = KnownArtist(
            match_first_name=match_first,
            match_last_name=match_last,
            match_quals=entry.get("match_quals"),
            resolved_first_name=entry.get("resolved_first_name"),
            resolved_last_name=entry.get("resolved_last_name"),
            resolved_title=entry.get("resolved_title"),
            resolved_quals=entry.get("resolved_quals"),
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
            notes=entry.get("notes"),
            is_seeded=True,
        )
        db.add(ka)
        added += 1

    db.commit()
    return {"added": added, "skipped": skipped, "total": added + skipped}
