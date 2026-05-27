"""add title_cased to works and title_cased_override to work_overrides

Revision ID: l2d4f6h8j0c1
Revises: k1c3e5g7i9b0
Create Date: 2026-05-27

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "l2d4f6h8j0c1"
down_revision: Union[str, Sequence[str], None] = "k1c3e5g7i9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("works", sa.Column("title_cased", sa.Text(), nullable=True))
    op.add_column(
        "work_overrides",
        sa.Column("title_cased_override", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("work_overrides", "title_cased_override")
    op.drop_column("works", "title_cased")
