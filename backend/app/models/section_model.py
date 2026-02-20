from sqlalchemy import Column, Text, Integer, ForeignKey, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid

from backend.app.db import Base


class Section(Base):
    __tablename__ = "sections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    import_id = Column(
        UUID(as_uuid=True), ForeignKey("imports.id", ondelete="CASCADE"), nullable=False
    )

    name = Column(Text, nullable=False)

    position = Column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("import_id", "name", name="sections_import_id_name_key"),
        UniqueConstraint(
            "import_id", "position", name="sections_import_id_position_key"
        ),
        Index("idx_sections_import", "import_id"),
    )
