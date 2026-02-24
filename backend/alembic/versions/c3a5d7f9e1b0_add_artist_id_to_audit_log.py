"""add artist_id to audit_log

Revision ID: c3a5d7f9e1b0
Revises: b2d4e6f8a0c1
Create Date: 2026-02-24

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = "c3a5d7f9e1b0"
down_revision: Union[str, Sequence[str], None] = "b2d4e6f8a0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "audit_logs",
        sa.Column(
            "artist_id",
            UUID(as_uuid=True),
            sa.ForeignKey("index_artists.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index("idx_audit_logs_artist", "audit_logs", ["artist_id"])


def downgrade() -> None:
    op.drop_index("idx_audit_logs_artist", table_name="audit_logs")
    op.drop_column("audit_logs", "artist_id")
