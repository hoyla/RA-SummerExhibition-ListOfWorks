import uuid

from sqlalchemy import TIMESTAMP, Column, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from backend.app.db import Base


class ImportSnapshot(Base):
    """Append-only snapshot of an import's full mutable state.

    Captured automatically immediately before a re-import (Update Import)
    rewrites the data, so the prior state can be diffed against the new one
    ("what changed, and why") and, if needed, restored wholesale.

    ``state`` is the serialised tree of sections -> works (raw + normalised
    columns) -> override + validation warnings, plus import-level warnings
    (see ``services/import_snapshot.serialize_import_state``). Nothing is ever
    mutated in place; each re-import adds a new row. This mirrors the existing
    ExportSnapshot / LowTagSnapshot append-only pattern.
    """

    __tablename__ = "import_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    import_id = Column(
        UUID(as_uuid=True),
        ForeignKey("imports.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Why the snapshot was taken. Currently always "pre_reimport"; kept as a
    # column so future snapshot kinds (manual save, pre-restore) can coexist.
    kind = Column(Text, nullable=False, server_default="pre_reimport")

    # Optional human-readable label for the snapshot list — e.g. the name of
    # the file the subsequent re-import pulled in.
    note = Column(Text, nullable=True)

    # The full serialised mutable state captured before the re-import.
    state = Column(JSONB, nullable=False)

    created_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (Index("idx_import_snapshots_import", "import_id"),)
