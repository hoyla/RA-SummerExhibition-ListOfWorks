"""Add notes column to work_overrides

Adds a free-text notes field to LoW overrides, matching the notes
field already available on index artist overrides.

Revision ID: i9a1b3c5d7e8
Revises: h8f0a2b4c6d7
Create Date: 2026-02-26
"""

from alembic import op
import sqlalchemy as sa

revision = "i9a1b3c5d7e8"
down_revision = "g7h8i9j0k1l2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("work_overrides", sa.Column("notes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("work_overrides", "notes")
