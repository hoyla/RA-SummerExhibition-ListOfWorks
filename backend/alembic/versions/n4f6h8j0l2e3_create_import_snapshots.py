"""create import_snapshots table

Revision ID: n4f6h8j0l2e3
Revises: m3e5g7i9k1d2
Create Date: 2026-06-06

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


# revision identifiers, used by Alembic.
revision: str = "n4f6h8j0l2e3"
down_revision: Union[str, Sequence[str], None] = "m3e5g7i9k1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "import_snapshots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "import_id",
            UUID(as_uuid=True),
            sa.ForeignKey("imports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False, server_default="pre_reimport"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("state", JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("idx_import_snapshots_import", "import_snapshots", ["import_id"])


def downgrade() -> None:
    op.drop_index("idx_import_snapshots_import", table_name="import_snapshots")
    op.drop_table("import_snapshots")
