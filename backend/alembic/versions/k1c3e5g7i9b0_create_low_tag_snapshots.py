"""create low_tag_snapshots table

Revision ID: k1c3e5g7i9b0
Revises: j0b2c4d6e8f9
Create Date: 2026-05-26

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = "k1c3e5g7i9b0"
down_revision: Union[str, Sequence[str], None] = "j0b2c4d6e8f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "low_tag_snapshots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "import_id",
            UUID(as_uuid=True),
            sa.ForeignKey("imports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("template_id", UUID(as_uuid=True), nullable=True),
        sa.Column("filename", sa.Text(), nullable=True),
        sa.Column(
            "encoding", sa.Text(), nullable=False, server_default="mac_roman"
        ),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column(
            "uploaded_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "idx_low_tag_snapshots_import", "low_tag_snapshots", ["import_id"]
    )


def downgrade() -> None:
    op.drop_index("idx_low_tag_snapshots_import", table_name="low_tag_snapshots")
    op.drop_table("low_tag_snapshots")
