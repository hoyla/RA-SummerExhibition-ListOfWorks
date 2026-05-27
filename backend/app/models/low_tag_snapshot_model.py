from sqlalchemy import Column, Text, TIMESTAMP, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid

from backend.app.db import Base


class LowTagSnapshot(Base):
    """An uploaded corrected List of Works InDesign Tagged Text file.

    Kept verbatim and append-only (one row per upload) so its diff against the
    import's *current* resolved data can be recomputed on demand — as the editor
    applies overrides or re-imports a corrected spreadsheet, re-viewing shows the
    resolved disparities drop off. See docs/reconcile.md.

    The tag content is stored inline (TEXT) rather than via the file-storage
    service: snapshots are few and modest, recompute needs the content every
    time, and inline storage keeps the row self-contained provenance with no
    orphaned files.
    """

    __tablename__ = "low_tag_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    import_id = Column(
        UUID(as_uuid=True),
        ForeignKey("imports.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Export template the file was produced with (null = default config). Pinned
    # per snapshot so the recomputed diff always uses the right styles.
    template_id = Column(UUID(as_uuid=True), nullable=True)
    filename = Column(Text, nullable=True)
    encoding = Column(Text, nullable=False, server_default="mac_roman")
    # The decoded tag content, stored verbatim (immutable provenance).
    raw_text = Column(Text, nullable=False)
    uploaded_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (Index("idx_low_tag_snapshots_import", "import_id"),)
