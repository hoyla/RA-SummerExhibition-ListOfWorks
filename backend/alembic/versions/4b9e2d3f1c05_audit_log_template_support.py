"""audit_log template support: nullable import_id, add template_id

Revision ID: 4b9e2d3f1c05
Revises: 3c7d1f8e2a01
Create Date: 2026-02-22

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = "4b9e2d3f1c05"
down_revision: Union[str, Sequence[str], None] = "3c7d1f8e2a01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Make import_id nullable so template-level events can be logged
    op.alter_column(
        "audit_logs",
        "import_id",
        existing_type=UUID(as_uuid=True),
        nullable=True,
    )
    # Add template_id column for template-level audit events
    op.add_column(
        "audit_logs",
        sa.Column(
            "template_id",
            UUID(as_uuid=True),
            sa.ForeignKey("rulesets.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("idx_audit_logs_template", "audit_logs", ["template_id"])


def downgrade() -> None:
    op.drop_index("idx_audit_logs_template", table_name="audit_logs")
    op.drop_column("audit_logs", "template_id")
    # Delete any rows with null import_id before making it non-nullable
    op.execute("DELETE FROM audit_logs WHERE import_id IS NULL")
    op.alter_column(
        "audit_logs",
        "import_id",
        existing_type=UUID(as_uuid=True),
        nullable=False,
    )
