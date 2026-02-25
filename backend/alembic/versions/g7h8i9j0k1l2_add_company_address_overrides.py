"""Add company and address fields to known_artists and index_artist_overrides

Revision ID: g7h8i9j0k1l2
Revises: f6d8e0a2b4c5
Create Date: 2026-02-25 20:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "g7h8i9j0k1l2"
down_revision = "h8f0a2b4c6d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Known Artists: allow explicit company name and address in resolved output
    op.add_column(
        "known_artists", sa.Column("resolved_company", sa.Text(), nullable=True)
    )
    op.add_column(
        "known_artists", sa.Column("resolved_address", sa.Text(), nullable=True)
    )

    # Known Artists: allow pre-baked title
    op.add_column(
        "known_artists", sa.Column("resolved_title", sa.Text(), nullable=True)
    )

    # Index Artist Overrides: allow explicit company name and address overrides
    op.add_column(
        "index_artist_overrides",
        sa.Column("company_override", sa.Text(), nullable=True),
    )
    op.add_column(
        "index_artist_overrides",
        sa.Column("address_override", sa.Text(), nullable=True),
    )
    # Index Artist Overrides: notes for human context
    op.add_column(
        "index_artist_overrides",
        sa.Column("notes", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("index_artist_overrides", "notes")
    op.drop_column("index_artist_overrides", "address_override")
    op.drop_column("index_artist_overrides", "company_override")
    op.drop_column("known_artists", "resolved_title")
    op.drop_column("known_artists", "resolved_address")
    op.drop_column("known_artists", "resolved_company")
