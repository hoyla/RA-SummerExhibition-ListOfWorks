"""Add known_artists lookup table

Revision ID: 9e4a6b2c1f03
Revises: 8d3f5a7b9e02
Create Date: 2026-02-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "9e4a6b2c1f03"
down_revision: Union[str, Sequence[str], None] = "8d3f5a7b9e02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "known_artists",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("match_first_name", sa.Text(), nullable=True),
        sa.Column("match_last_name", sa.Text(), nullable=True),
        sa.Column("resolved_first_name", sa.Text(), nullable=True),
        sa.Column("resolved_last_name", sa.Text(), nullable=True),
        sa.Column("resolved_quals", sa.Text(), nullable=True),
        sa.Column("resolved_second_artist", sa.Text(), nullable=True),
        sa.Column("resolved_is_company", sa.Boolean(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "match_first_name",
            "match_last_name",
            name="uq_known_artist_match",
        ),
    )


def downgrade() -> None:
    op.drop_table("known_artists")
