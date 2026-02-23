"""Add name override fields to index_artist_overrides

Revision ID: a1b2c3d4e5f6
Revises: 9e4a6b2c1f03
Create Date: 2026-02-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "9e4a6b2c1f03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "index_artist_overrides",
        sa.Column("first_name_override", sa.Text(), nullable=True),
    )
    op.add_column(
        "index_artist_overrides",
        sa.Column("last_name_override", sa.Text(), nullable=True),
    )
    op.add_column(
        "index_artist_overrides",
        sa.Column("title_override", sa.Text(), nullable=True),
    )
    op.add_column(
        "index_artist_overrides",
        sa.Column("quals_override", sa.Text(), nullable=True),
    )
    op.add_column(
        "index_artist_overrides",
        sa.Column("second_artist_override", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("index_artist_overrides", "second_artist_override")
    op.drop_column("index_artist_overrides", "quals_override")
    op.drop_column("index_artist_overrides", "title_override")
    op.drop_column("index_artist_overrides", "last_name_override")
    op.drop_column("index_artist_overrides", "first_name_override")
