"""add disk_filename to imports

Revision ID: 2a8c3f9e1b04
Revises: 15b18f4d74e3
Create Date: 2026-02-22

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2a8c3f9e1b04"
down_revision: Union[str, Sequence[str], None] = "15b18f4d74e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("imports", sa.Column("disk_filename", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("imports", "disk_filename")
