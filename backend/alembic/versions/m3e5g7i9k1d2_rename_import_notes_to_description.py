"""rename imports.notes to imports.description

The ``imports.notes`` column has existed (nullable) but was never written to:
it surfaced in the import-list responses yet had no way to be set. It is being
promoted to a user-editable free-text "description" field, renamed here to
avoid colliding conceptually with the unrelated "Import notes" validation
panel in the UI. The column is empty in practice, so the rename is data-safe.

Revision ID: m3e5g7i9k1d2
Revises: l2d4f6h8j0c1
Create Date: 2026-06-06

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "m3e5g7i9k1d2"
down_revision: Union[str, Sequence[str], None] = "l2d4f6h8j0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("imports", "notes", new_column_name="description")


def downgrade() -> None:
    op.alter_column("imports", "description", new_column_name="notes")
