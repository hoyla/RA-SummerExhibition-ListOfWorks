"""Add shared-surname flags for multi-artist entries

When an additional artist shares Artist 1's surname (e.g. siblings,
married couples), the surname is not repeated in the rendered output.

Adds boolean columns to index_artists, index_artist_overrides, and
known_artists.

Revision ID: j0b2c4d6e8f9
Revises: i9a1b3c5d7e8
Create Date: 2026-03-01
"""

from alembic import op
import sqlalchemy as sa

revision = "j0b2c4d6e8f9"
down_revision = "i9a1b3c5d7e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IndexArtist — normalised flags (default False)
    op.add_column(
        "index_artists",
        sa.Column(
            "artist2_shared_surname",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "index_artists",
        sa.Column(
            "artist3_shared_surname",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # IndexArtistOverride — tri-state overrides (nullable)
    op.add_column(
        "index_artist_overrides",
        sa.Column("artist2_shared_surname_override", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "index_artist_overrides",
        sa.Column("artist3_shared_surname_override", sa.Boolean(), nullable=True),
    )

    # KnownArtist — resolved flags (nullable)
    op.add_column(
        "known_artists",
        sa.Column("resolved_artist2_shared_surname", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "known_artists",
        sa.Column("resolved_artist3_shared_surname", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("known_artists", "resolved_artist3_shared_surname")
    op.drop_column("known_artists", "resolved_artist2_shared_surname")
    op.drop_column("index_artist_overrides", "artist3_shared_surname_override")
    op.drop_column("index_artist_overrides", "artist2_shared_surname_override")
    op.drop_column("index_artists", "artist3_shared_surname")
    op.drop_column("index_artists", "artist2_shared_surname")
