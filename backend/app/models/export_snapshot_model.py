from sqlalchemy import Column, Text, TIMESTAMP, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
import uuid

from backend.app.db import Base


class ExportSnapshot(Base):
    __tablename__ = "export_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    import_id = Column(
        UUID(as_uuid=True),
        ForeignKey("imports.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Which template was used (null = default config)
    template_id = Column(UUID(as_uuid=True), nullable=True)

    # The full resolved export data snapshot (output of _collect_export_data)
    snapshot_data = Column(JSONB, nullable=False)

    exported_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("idx_export_snapshots_import", "import_id"),
        Index("idx_export_snapshots_lookup", "import_id", "template_id"),
    )
