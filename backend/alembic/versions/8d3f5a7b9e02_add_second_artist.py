"""Add second_artist column to index_artists

Revision ID: 8d3f5a7b9e02
Revises: 7c2e4f6a8d01
Create Date: 2026-02-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "8d3f5a7b9e02"
down_revision: Union[str, Sequence[str], None] = "7c2e4f6a8d01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "index_artists",
        sa.Column("second_artist", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("index_artists", "second_artist")
