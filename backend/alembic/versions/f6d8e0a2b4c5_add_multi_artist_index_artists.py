"""Add multi-artist columns to index_artists

Replaces the single 'second_artist' text column with structured
multi-artist fields (artist2/artist3 first_name, last_name, quals)
and per-artist RA styling booleans.

Revision ID: f6d8e0a2b4c5
Revises: e5c7d9f1a3b4
Create Date: 2026-02-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f6d8e0a2b4c5"
down_revision: Union[str, Sequence[str], None] = "e5c7d9f1a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Multi-artist name fields
    op.add_column(
        "index_artists",
        sa.Column("artist2_first_name", sa.Text(), nullable=True),
    )
    op.add_column(
        "index_artists",
        sa.Column("artist2_last_name", sa.Text(), nullable=True),
    )
    op.add_column(
        "index_artists",
        sa.Column("artist2_quals", sa.Text(), nullable=True),
    )
    op.add_column(
        "index_artists",
        sa.Column("artist3_first_name", sa.Text(), nullable=True),
    )
    op.add_column(
        "index_artists",
        sa.Column("artist3_last_name", sa.Text(), nullable=True),
    )
    op.add_column(
        "index_artists",
        sa.Column("artist3_quals", sa.Text(), nullable=True),
    )

    # Per-artist RA styling flags
    op.add_column(
        "index_artists",
        sa.Column(
            "artist1_ra_styled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "index_artists",
        sa.Column(
            "artist2_ra_styled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "index_artists",
        sa.Column(
            "artist3_ra_styled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # Drop the old flat second_artist column
    op.drop_column("index_artists", "second_artist")


def downgrade() -> None:
    op.add_column(
        "index_artists",
        sa.Column("second_artist", sa.Text(), nullable=True),
    )

    op.drop_column("index_artists", "artist3_ra_styled")
    op.drop_column("index_artists", "artist2_ra_styled")
    op.drop_column("index_artists", "artist1_ra_styled")
    op.drop_column("index_artists", "artist3_quals")
    op.drop_column("index_artists", "artist3_last_name")
    op.drop_column("index_artists", "artist3_first_name")
    op.drop_column("index_artists", "artist2_quals")
    op.drop_column("index_artists", "artist2_last_name")
    op.drop_column("index_artists", "artist2_first_name")
