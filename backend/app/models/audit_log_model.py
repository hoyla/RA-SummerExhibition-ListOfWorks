from sqlalchemy import Column, Text, TIMESTAMP, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid

from backend.app.db import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Null for template-level actions
    import_id = Column(
        UUID(as_uuid=True),
        ForeignKey("imports.id", ondelete="CASCADE"),
        nullable=True,
    )

    # Null for import-level actions
    work_id = Column(
        UUID(as_uuid=True),
        ForeignKey("works.id", ondelete="CASCADE"),
        nullable=True,
    )

    # Null for non-index actions
    artist_id = Column(
        UUID(as_uuid=True),
        ForeignKey("index_artists.id", ondelete="CASCADE"),
        nullable=True,
    )

    # Null for non-template actions
    template_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rulesets.id", ondelete="SET NULL"),
        nullable=True,
    )

    # e.g. 'override_set', 'override_deleted', 'work_excluded', 'work_included',
    #      'template_created', 'template_updated', 'template_deleted', 'template_duplicated'
    action = Column(Text, nullable=False)

    # Field name that changed, null for non-field actions
    field = Column(Text, nullable=True)

    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)

    created_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("idx_audit_logs_import", "import_id"),
        Index("idx_audit_logs_work", "work_id"),
        Index("idx_audit_logs_artist", "artist_id"),
        Index("idx_audit_logs_template", "template_id"),
    )
