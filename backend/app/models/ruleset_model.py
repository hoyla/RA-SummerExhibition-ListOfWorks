from sqlalchemy import Column, Text, Integer, Boolean, TIMESTAMP, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
import uuid

from backend.app.db import Base


class Ruleset(Base):
    __tablename__ = "rulesets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    name = Column(Text, nullable=False)

    version = Column(Integer, nullable=False, server_default="1")

    config = Column(JSONB, nullable=False)

    config_hash = Column(Text, nullable=False)

    created_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    archived = Column(Boolean, nullable=False, server_default="false")

    __table_args__ = (
        Index("idx_rulesets_hash", "config_hash"),
        Index("idx_rulesets_config_gin", "config", postgresql_using="gin"),
    )
