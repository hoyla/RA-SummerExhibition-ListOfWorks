"""create export_snapshots table

Revision ID: 3c7d1f8e2a01
Revises: 2a8c3f9e1b04
Create Date: 2026-02-22

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


# revision identifiers, used by Alembic.
revision: str = "3c7d1f8e2a01"
down_revision: Union[str, Sequence[str], None] = "2a8c3f9e1b04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "export_snapshots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "import_id",
            UUID(as_uuid=True),
            sa.ForeignKey("imports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("template_id", UUID(as_uuid=True), nullable=True),
        sa.Column("snapshot_data", JSONB, nullable=False),
        sa.Column(
            "exported_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("idx_export_snapshots_import", "export_snapshots", ["import_id"])
    op.create_index(
        "idx_export_snapshots_lookup",
        "export_snapshots",
        ["import_id", "template_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_export_snapshots_lookup", table_name="export_snapshots")
    op.drop_index("idx_export_snapshots_import", table_name="export_snapshots")
    op.drop_table("export_snapshots")
