from sqlalchemy import Column, Text, TIMESTAMP, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid

from backend.app.db import Base


class ValidationWarning(Base):
    __tablename__ = "validation_warnings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    import_id = Column(
        UUID(as_uuid=True),
        ForeignKey("imports.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Null when warning is at import level (e.g. duplicate filename)
    work_id = Column(
        UUID(as_uuid=True),
        ForeignKey("works.id", ondelete="CASCADE"),
        nullable=True,
    )

    # Short machine-readable type, e.g. 'missing_title', 'unrecognised_price'
    warning_type = Column(Text, nullable=False)

    message = Column(Text, nullable=False)

    created_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("idx_validation_warnings_import", "import_id"),
        Index("idx_validation_warnings_work", "work_id"),
    )
