from sqlalchemy import (
    Column,
    Text,
    Integer,
    Boolean,
    Numeric,
    ForeignKey,
    TIMESTAMP,
    UniqueConstraint,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid

from backend.app.db import Base


class Work(Base):
    __tablename__ = "works"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    import_id = Column(
        UUID(as_uuid=True),
        ForeignKey("imports.id", ondelete="CASCADE"),
        nullable=False,
    )

    section_id = Column(
        UUID(as_uuid=True),
        ForeignKey("sections.id", ondelete="CASCADE"),
        nullable=False,
    )

    position_in_section = Column(Integer, nullable=False)

    # RAW LAYER
    raw_cat_no = Column(Text, nullable=True)
    raw_gallery = Column(Text, nullable=True)
    raw_title = Column(Text, nullable=True)
    raw_artist = Column(Text, nullable=True)
    raw_price = Column(Text, nullable=True)
    raw_edition = Column(Text, nullable=True)
    raw_artwork = Column(Text, nullable=True)
    raw_medium = Column(Text, nullable=True)

    # NORMALISED LAYER
    number = Column(Integer, nullable=True)
    title = Column(Text, nullable=True)
    artist_name = Column(Text, nullable=True)
    artist_honorifics = Column(Text, nullable=True)
    price_numeric = Column(Numeric(12, 2), nullable=True)
    price_text = Column(Text, nullable=True)
    edition_total = Column(Integer, nullable=True)
    edition_price_numeric = Column(Numeric(12, 2), nullable=True)
    artwork = Column(Integer, nullable=True)
    medium = Column(Text, nullable=True)

    include_in_export = Column(Boolean, nullable=False, server_default="true")

    created_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "section_id",
            "position_in_section",
            name="unique_position_per_section",
        ),
        Index("idx_works_import", "import_id"),
        Index("idx_works_section", "section_id"),
        Index("idx_works_position", "section_id", "position_in_section"),
    )
