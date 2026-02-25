"""Add multi-artist columns to known_artists

Revision ID: e5c7d9f1a3b4
Revises: d4b6e8f0a2c3
Create Date: 2026-02-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e5c7d9f1a3b4"
down_revision: Union[str, Sequence[str], None] = "d4b6e8f0a2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Match criteria
    op.add_column("known_artists", sa.Column("match_quals", sa.Text(), nullable=True))

    # Multi-artist resolved fields (replacing old resolved_second_artist)
    op.add_column(
        "known_artists",
        sa.Column("resolved_artist2_first_name", sa.Text(), nullable=True),
    )
    op.add_column(
        "known_artists",
        sa.Column("resolved_artist2_last_name", sa.Text(), nullable=True),
    )
    op.add_column(
        "known_artists",
        sa.Column("resolved_artist2_quals", sa.Text(), nullable=True),
    )
    op.add_column(
        "known_artists",
        sa.Column("resolved_artist3_first_name", sa.Text(), nullable=True),
    )
    op.add_column(
        "known_artists",
        sa.Column("resolved_artist3_last_name", sa.Text(), nullable=True),
    )
    op.add_column(
        "known_artists",
        sa.Column("resolved_artist3_quals", sa.Text(), nullable=True),
    )

    # Per-artist RA styling flags
    op.add_column(
        "known_artists",
        sa.Column("resolved_artist1_ra_styled", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "known_artists",
        sa.Column("resolved_artist2_ra_styled", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "known_artists",
        sa.Column("resolved_artist3_ra_styled", sa.Boolean(), nullable=True),
    )

    # Drop the old flat second_artist column
    op.drop_column("known_artists", "resolved_second_artist")

    # Update unique constraint to include match_quals
    op.drop_constraint("uq_known_artist_match", "known_artists", type_="unique")
    op.create_unique_constraint(
        "uq_known_artist_match",
        "known_artists",
        ["match_first_name", "match_last_name", "match_quals"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_known_artist_match", "known_artists", type_="unique")
    op.create_unique_constraint(
        "uq_known_artist_match",
        "known_artists",
        ["match_first_name", "match_last_name"],
    )

    op.add_column(
        "known_artists",
        sa.Column("resolved_second_artist", sa.Text(), nullable=True),
    )

    op.drop_column("known_artists", "resolved_artist3_ra_styled")
    op.drop_column("known_artists", "resolved_artist2_ra_styled")
    op.drop_column("known_artists", "resolved_artist1_ra_styled")
    op.drop_column("known_artists", "resolved_artist3_quals")
    op.drop_column("known_artists", "resolved_artist3_last_name")
    op.drop_column("known_artists", "resolved_artist3_first_name")
    op.drop_column("known_artists", "resolved_artist2_quals")
    op.drop_column("known_artists", "resolved_artist2_last_name")
    op.drop_column("known_artists", "resolved_artist2_first_name")
    op.drop_column("known_artists", "match_quals")
