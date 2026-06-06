import uuid

from sqlalchemy import TIMESTAMP, Column, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from backend.app.db import Base


class Import(Base):
    __tablename__ = "imports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    filename = Column(Text, nullable=False)
    disk_filename = Column(Text, nullable=True)  # UUID-prefixed name on disk
    # Free-text, user-editable note about this import (max 256 chars, enforced
    # at the API layer). Distinct from the "Import notes" validation panel.
    description = Column(Text, nullable=True)

    # 'list_of_works' | 'artists_index'
    product_type = Column(Text, nullable=False, server_default="list_of_works")

    uploaded_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
