from sqlalchemy import Column, Boolean, Text, ForeignKey, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from backend.app.db import Base


class IndexArtistOverride(Base):
    """User-applied overrides for an IndexArtist entry.

    Each nullable column represents an overridable field.  ``None`` means
    "use the importer's auto-detected value"; a non-None value means the
    user has explicitly set it.

    The ``""`` (empty-string) convention means "clear this field" — i.e.
    force it to None/blank regardless of the normalised or known-artist
    value.
    """

    __tablename__ = "index_artist_overrides"

    artist_id = Column(
        UUID(as_uuid=True),
        ForeignKey("index_artists.id", ondelete="CASCADE"),
        primary_key=True,
    )

    is_company_override = Column(Boolean, nullable=True)

    first_name_override = Column(Text, nullable=True)
    last_name_override = Column(Text, nullable=True)
    title_override = Column(Text, nullable=True)
    quals_override = Column(Text, nullable=True)

    # Multi-artist override fields
    artist2_first_name_override = Column(Text, nullable=True)
    artist2_last_name_override = Column(Text, nullable=True)
    artist2_quals_override = Column(Text, nullable=True)
    artist3_first_name_override = Column(Text, nullable=True)
    artist3_last_name_override = Column(Text, nullable=True)
    artist3_quals_override = Column(Text, nullable=True)

    # Per-artist RA styling overrides
    artist1_ra_styled_override = Column(Boolean, nullable=True)
    artist2_ra_styled_override = Column(Boolean, nullable=True)
    artist3_ra_styled_override = Column(Boolean, nullable=True)

    updated_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
