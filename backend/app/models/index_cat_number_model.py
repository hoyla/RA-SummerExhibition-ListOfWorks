from sqlalchemy import (
    Column,
    Text,
    Integer,
    ForeignKey,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid

from backend.app.db import Base


class IndexCatNumber(Base):
    __tablename__ = "index_cat_numbers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    artist_id = Column(
        UUID(as_uuid=True),
        ForeignKey("index_artists.id", ondelete="CASCADE"),
        nullable=False,
    )

    cat_no = Column(Integer, nullable=False)

    # "Courtesy of Cristea Roberts Gallery", etc. NULL = no courtesy.
    courtesy = Column(Text, nullable=True)

    # Which spreadsheet row this cat number originally came from.
    # Used to power the unmerge feature when duplicate names are merged.
    source_row = Column(Integer, nullable=True)

    artist = relationship("IndexArtist", back_populates="cat_numbers")

    __table_args__ = (
        Index("idx_index_cat_numbers_artist", "artist_id"),
        Index("idx_index_cat_numbers_cat_no", "cat_no"),
    )
