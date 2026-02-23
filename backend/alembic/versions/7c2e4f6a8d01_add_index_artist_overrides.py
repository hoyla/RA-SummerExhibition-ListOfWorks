"""Add index_artist_overrides table

Revision ID: 7c2e4f6a8d01
Revises: 5a1f3d7e4b02
Create Date: 2026-02-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "7c2e4f6a8d01"
down_revision: Union[str, Sequence[str], None] = "5a1f3d7e4b02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "index_artist_overrides",
        sa.Column(
            "artist_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("index_artists.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("is_company_override", sa.Boolean(), nullable=True),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("index_artist_overrides")
