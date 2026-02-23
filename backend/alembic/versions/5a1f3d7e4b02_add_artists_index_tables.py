"""Add artists index tables and product_type to imports

Revision ID: 5a1f3d7e4b02
Revises: 4b9e2d3f1c05
Create Date: 2026-02-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "5a1f3d7e4b02"
down_revision: Union[str, Sequence[str], None] = "4b9e2d3f1c05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- product_type on imports --
    op.add_column(
        "imports",
        sa.Column(
            "product_type",
            sa.Text(),
            nullable=False,
            server_default="list_of_works",
        ),
    )

    # -- index_artists --
    op.create_table(
        "index_artists",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "import_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("imports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("row_number", sa.Integer(), nullable=True),
        # raw layer
        sa.Column("raw_title", sa.Text(), nullable=True),
        sa.Column("raw_first_name", sa.Text(), nullable=True),
        sa.Column("raw_last_name", sa.Text(), nullable=True),
        sa.Column("raw_quals", sa.Text(), nullable=True),
        sa.Column("raw_company", sa.Text(), nullable=True),
        sa.Column("raw_address", sa.Text(), nullable=True),
        # normalised layer
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("first_name", sa.Text(), nullable=True),
        sa.Column("last_name", sa.Text(), nullable=True),
        sa.Column("quals", sa.Text(), nullable=True),
        sa.Column("company", sa.Text(), nullable=True),
        sa.Column(
            "is_ra_member",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column(
            "is_company",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column("sort_key", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "include_in_export",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("idx_index_artists_import", "index_artists", ["import_id"])
    op.create_index(
        "idx_index_artists_sort", "index_artists", ["import_id", "sort_key"]
    )

    # -- index_cat_numbers --
    op.create_table(
        "index_cat_numbers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "artist_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("index_artists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cat_no", sa.Integer(), nullable=False),
        sa.Column("courtesy", sa.Text(), nullable=True),
    )
    op.create_index("idx_index_cat_numbers_artist", "index_cat_numbers", ["artist_id"])
    op.create_index("idx_index_cat_numbers_cat_no", "index_cat_numbers", ["cat_no"])


def downgrade() -> None:
    op.drop_table("index_cat_numbers")
    op.drop_table("index_artists")
    op.drop_column("imports", "product_type")
