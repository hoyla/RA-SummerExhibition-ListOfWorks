from sqlalchemy import Column, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid

from backend.app.db import Base


class Import(Base):
    __tablename__ = "imports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    filename = Column(Text, nullable=False)
    disk_filename = Column(Text, nullable=True)  # UUID-prefixed name on disk
    notes = Column(Text, nullable=True)

    uploaded_at = Column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
