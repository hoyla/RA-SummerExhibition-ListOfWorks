"""Add is_seeded flag to known_artists

Allows the UI to distinguish built-in seed entries (read-only,
duplicatable) from user-created entries (fully editable).

Revision ID: h8f0a2b4c6d7
Revises: g7e9f1a3b5d6
Create Date: 2026-02-25
"""

from alembic import op
import sqlalchemy as sa

revision = "h8f0a2b4c6d7"
down_revision = "g7e9f1a3b5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "known_artists",
        sa.Column(
            "is_seeded",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    # Widen unique constraint so a user copy can coexist with the seeded original
    op.drop_constraint("uq_known_artist_match", "known_artists", type_="unique")
    op.create_unique_constraint(
        "uq_known_artist_match",
        "known_artists",
        ["match_first_name", "match_last_name", "match_quals", "is_seeded"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_known_artist_match", "known_artists", type_="unique")
    op.create_unique_constraint(
        "uq_known_artist_match",
        "known_artists",
        ["match_first_name", "match_last_name", "match_quals"],
    )
    op.drop_column("known_artists", "is_seeded")
