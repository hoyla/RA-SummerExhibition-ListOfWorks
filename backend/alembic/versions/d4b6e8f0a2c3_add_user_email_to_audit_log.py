"""add user_email to audit_log

Revision ID: d4b6e8f0a2c3
Revises: c3a5d7f9e1b0
Create Date: 2026-02-24

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d4b6e8f0a2c3"
down_revision: Union[str, None] = "c3a5d7f9e1b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("audit_logs", sa.Column("user_email", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("audit_logs", "user_email")
