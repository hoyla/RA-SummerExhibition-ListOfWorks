from sqlalchemy import (
    Column,
    Text,
    TIMESTAMP,
    ForeignKey,
    CheckConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid

from backend.app.db import Base


class Export(Base):
    __tablename__ = "exports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    import_id = Column(
        UUID(as_uuid=True),
        ForeignKey("imports.id", ondelete="CASCADE"),
        nullable=False,
    )

    ruleset_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rulesets.id"),
        nullable=False,
    )

    export_type = Column(Text, nullable=False)

    section_id = Column(
        UUID(as_uuid=True),
        ForeignKey("sections.id"),
        nullable=True,
    )

    work_id = Column(
        UUID(as_uuid=True),
        ForeignKey("works.id"),
        nullable=True,
    )

    file_path = Column(Text, nullable=False)

    created_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            """
            (
                export_type = 'full' AND section_id IS NULL AND work_id IS NULL
            )
            OR
            (
                export_type = 'section' AND section_id IS NOT NULL
            )
            OR
            (
                export_type = 'single_work' AND work_id IS NOT NULL
            )
            """,
            name="export_scope_check",
        ),
    )
