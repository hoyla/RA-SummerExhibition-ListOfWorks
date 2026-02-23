from sqlalchemy import (
    Column,
    Text,
    Integer,
    Boolean,
    ForeignKey,
    TIMESTAMP,
    UniqueConstraint,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from backend.app.db import Base


class IndexArtist(Base):
    __tablename__ = "index_artists"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    import_id = Column(
        UUID(as_uuid=True),
        ForeignKey("imports.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Spreadsheet row number for traceability
    row_number = Column(Integer, nullable=True)

    # RAW LAYER — verbatim from spreadsheet
    raw_title = Column(Text, nullable=True)  # "Sir", "Prof.", "The late"
    raw_first_name = Column(Text, nullable=True)
    raw_last_name = Column(Text, nullable=True)
    raw_quals = Column(Text, nullable=True)  # "CBE RA", "HON RA"
    raw_company = Column(Text, nullable=True)  # Company column (usually empty)
    raw_address = Column(Text, nullable=True)  # Address 1 column

    # NORMALISED LAYER
    title = Column(Text, nullable=True)  # Cleaned title
    first_name = Column(Text, nullable=True)  # Cleaned first name
    last_name = Column(Text, nullable=True)  # Cleaned last name
    quals = Column(Text, nullable=True)  # Cleaned qualifications
    company = Column(Text, nullable=True)  # Detected company name
    second_artist = Column(Text, nullable=True)  # "and Matthias Sauerbruch" suffix
    is_ra_member = Column(Boolean, nullable=False, server_default="false")
    is_company = Column(Boolean, nullable=False, server_default="false")

    # Sort key for alphabetical export ordering
    sort_key = Column(Text, nullable=False, server_default="")

    include_in_export = Column(Boolean, nullable=False, server_default="true")

    created_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    cat_numbers = relationship(
        "IndexCatNumber",
        back_populates="artist",
        cascade="all, delete-orphan",
        order_by="IndexCatNumber.cat_no",
    )

    __table_args__ = (
        Index("idx_index_artists_import", "import_id"),
        Index("idx_index_artists_sort", "import_id", "sort_key"),
    )
