"""initial schema baseline

Revision ID: 15b18f4d74e3
Revises:
Create Date: 2026-02-22 15:40:44.293289

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "15b18f4d74e3"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- imports ---
    op.create_table(
        "imports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "uploaded_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # --- sections ---
    op.create_table(
        "sections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "import_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("imports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.UniqueConstraint("import_id", "name", name="sections_import_id_name_key"),
        sa.UniqueConstraint(
            "import_id", "position", name="sections_import_id_position_key"
        ),
    )
    op.create_index("idx_sections_import", "sections", ["import_id"])

    # --- works ---
    op.create_table(
        "works",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "import_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("imports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "section_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position_in_section", sa.Integer(), nullable=False),
        # Raw layer
        sa.Column("raw_cat_no", sa.Text(), nullable=True),
        sa.Column("raw_gallery", sa.Text(), nullable=True),
        sa.Column("raw_title", sa.Text(), nullable=True),
        sa.Column("raw_artist", sa.Text(), nullable=True),
        sa.Column("raw_price", sa.Text(), nullable=True),
        sa.Column("raw_edition", sa.Text(), nullable=True),
        sa.Column("raw_artwork", sa.Text(), nullable=True),
        sa.Column("raw_medium", sa.Text(), nullable=True),
        # Normalised layer
        sa.Column("number", sa.Integer(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("artist_name", sa.Text(), nullable=True),
        sa.Column("artist_honorifics", sa.Text(), nullable=True),
        sa.Column("price_numeric", sa.Numeric(12, 2), nullable=True),
        sa.Column("price_text", sa.Text(), nullable=True),
        sa.Column("edition_total", sa.Integer(), nullable=True),
        sa.Column("edition_price_numeric", sa.Numeric(12, 2), nullable=True),
        sa.Column("artwork", sa.Integer(), nullable=True),
        sa.Column("medium", sa.Text(), nullable=True),
        sa.Column(
            "include_in_export",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "section_id",
            "position_in_section",
            name="unique_position_per_section",
        ),
    )
    op.create_index("idx_works_import", "works", ["import_id"])
    op.create_index("idx_works_section", "works", ["section_id"])
    op.create_index(
        "idx_works_position", "works", ["section_id", "position_in_section"]
    )

    # --- work_overrides ---
    op.create_table(
        "work_overrides",
        sa.Column(
            "work_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("works.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("title_override", sa.Text(), nullable=True),
        sa.Column("artist_name_override", sa.Text(), nullable=True),
        sa.Column("artist_honorifics_override", sa.Text(), nullable=True),
        sa.Column("price_numeric_override", sa.Numeric(12, 2), nullable=True),
        sa.Column("price_text_override", sa.Text(), nullable=True),
        sa.Column("edition_total_override", sa.Integer(), nullable=True),
        sa.Column("edition_price_numeric_override", sa.Numeric(12, 2), nullable=True),
        sa.Column("artwork_override", sa.Integer(), nullable=True),
        sa.Column("medium_override", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # --- rulesets ---
    op.create_table(
        "rulesets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("config_type", sa.Text(), nullable=False, server_default="template"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column("config_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("slug", sa.Text(), nullable=True),
    )
    op.create_index("idx_rulesets_hash", "rulesets", ["config_hash"])
    op.create_index(
        "idx_rulesets_config_gin",
        "rulesets",
        ["config"],
        postgresql_using="gin",
    )

    # --- validation_warnings ---
    op.create_table(
        "validation_warnings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "import_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("imports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "work_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("works.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("warning_type", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "idx_validation_warnings_import", "validation_warnings", ["import_id"]
    )
    op.create_index("idx_validation_warnings_work", "validation_warnings", ["work_id"])

    # --- audit_logs ---
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "import_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("imports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "work_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("works.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("field", sa.Text(), nullable=True),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("idx_audit_logs_import", "audit_logs", ["import_id"])
    op.create_index("idx_audit_logs_work", "audit_logs", ["work_id"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("validation_warnings")
    op.drop_table("rulesets")
    op.drop_table("work_overrides")
    op.drop_table("works")
    op.drop_table("sections")
    op.drop_table("imports")
