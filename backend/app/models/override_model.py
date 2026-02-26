from sqlalchemy import Column, Text, Integer, Numeric, TIMESTAMP, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from backend.app.db import Base


class WorkOverride(Base):
    __tablename__ = "work_overrides"

    work_id = Column(
        UUID(as_uuid=True),
        ForeignKey("works.id", ondelete="CASCADE"),
        primary_key=True,
    )

    title_override = Column(Text, nullable=True)
    artist_name_override = Column(Text, nullable=True)
    artist_honorifics_override = Column(Text, nullable=True)

    price_numeric_override = Column(Numeric(12, 2), nullable=True)
    price_text_override = Column(Text, nullable=True)

    edition_total_override = Column(Integer, nullable=True)
    edition_price_numeric_override = Column(Numeric(12, 2), nullable=True)

    artwork_override = Column(Integer, nullable=True)
    medium_override = Column(Text, nullable=True)

    notes = Column(Text, nullable=True)

    updated_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
