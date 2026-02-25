"""Add multi-artist override columns to index_artist_overrides

Replaces the single 'second_artist_override' text column with structured
per-artist override fields and RA styling override booleans.

Revision ID: g7e9f1a3b5d6
Revises: f6d8e0a2b4c5
Create Date: 2026-02-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "g7e9f1a3b5d6"
down_revision: Union[str, Sequence[str], None] = "f6d8e0a2b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Multi-artist override fields
    op.add_column(
        "index_artist_overrides",
        sa.Column("artist2_first_name_override", sa.Text(), nullable=True),
    )
    op.add_column(
        "index_artist_overrides",
        sa.Column("artist2_last_name_override", sa.Text(), nullable=True),
    )
    op.add_column(
        "index_artist_overrides",
        sa.Column("artist2_quals_override", sa.Text(), nullable=True),
    )
    op.add_column(
        "index_artist_overrides",
        sa.Column("artist3_first_name_override", sa.Text(), nullable=True),
    )
    op.add_column(
        "index_artist_overrides",
        sa.Column("artist3_last_name_override", sa.Text(), nullable=True),
    )
    op.add_column(
        "index_artist_overrides",
        sa.Column("artist3_quals_override", sa.Text(), nullable=True),
    )

    # Per-artist RA styling overrides
    op.add_column(
        "index_artist_overrides",
        sa.Column("artist1_ra_styled_override", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "index_artist_overrides",
        sa.Column("artist2_ra_styled_override", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "index_artist_overrides",
        sa.Column("artist3_ra_styled_override", sa.Boolean(), nullable=True),
    )

    # Drop the old flat second_artist_override column
    op.drop_column("index_artist_overrides", "second_artist_override")


def downgrade() -> None:
    op.add_column(
        "index_artist_overrides",
        sa.Column("second_artist_override", sa.Text(), nullable=True),
    )
    op.drop_column("index_artist_overrides", "artist3_ra_styled_override")
    op.drop_column("index_artist_overrides", "artist2_ra_styled_override")
    op.drop_column("index_artist_overrides", "artist1_ra_styled_override")
    op.drop_column("index_artist_overrides", "artist3_quals_override")
    op.drop_column("index_artist_overrides", "artist3_last_name_override")
    op.drop_column("index_artist_overrides", "artist3_first_name_override")
    op.drop_column("index_artist_overrides", "artist2_quals_override")
    op.drop_column("index_artist_overrides", "artist2_last_name_override")
    op.drop_column("index_artist_overrides", "artist2_first_name_override")
