"""Add source_row to index_cat_numbers

Revision ID: b2d4e6f8a0c1
Revises: a1b2c3d4e5f6
Create Date: 2026-02-24
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b2d4e6f8a0c1"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "index_cat_numbers",
        sa.Column("source_row", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("index_cat_numbers", "source_row")
