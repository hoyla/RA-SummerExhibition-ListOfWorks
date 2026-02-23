from sqlalchemy import (
    Column,
    Text,
    Boolean,
    TIMESTAMP,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid

from backend.app.db import Base


class KnownArtist(Base):
    """Lookup table of known artists.

    Entries map raw spreadsheet values to the correct normalised output.
    During import, the importer checks this table before applying
    heuristic normalisation.  This allows recurring entries (many artists
    appear year after year) to be corrected once and applied automatically.
    """

    __tablename__ = "known_artists"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # --- Match criteria (what appears in the spreadsheet) ---
    # Both fields are used for matching; a NULL match field matches any value.
    match_first_name = Column(Text, nullable=True)
    match_last_name = Column(Text, nullable=True)

    # --- Resolved output (what the entry should become) ---
    resolved_first_name = Column(Text, nullable=True)
    resolved_last_name = Column(Text, nullable=True)
    resolved_quals = Column(Text, nullable=True)
    resolved_second_artist = Column(Text, nullable=True)
    resolved_is_company = Column(Boolean, nullable=True)

    # Human-readable note explaining why this override exists
    notes = Column(Text, nullable=True)

    created_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "match_first_name",
            "match_last_name",
            name="uq_known_artist_match",
        ),
    )
