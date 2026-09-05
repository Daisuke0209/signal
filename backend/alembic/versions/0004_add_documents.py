"""Add uploaded document metadata.

Revision ID: 0004_add_documents
Revises: 0003_speaker_labels
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004_add_documents"
down_revision: str | None = "0003_speaker_labels"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    status = postgresql.ENUM(
        "pending",
        "processing",
        "ready",
        "failed",
        "text_unavailable",
        name="document_processing_status",
        create_type=False,
    )
    op.execute(
        "DO $$ BEGIN CREATE TYPE document_processing_status AS ENUM "
        "('pending', 'processing', 'ready', 'failed', 'text_unavailable'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
    )
    op.create_table(
        "documents",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.UUID(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(length=36), nullable=False),
        sa.Column(
            "processing_status",
            status,
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("processing_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="documents_organization_id_organizations_id_fk",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_user_id"],
            ["users.id"],
            name="documents_uploaded_by_user_id_users_id_fk",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index("documents_organization_id_idx", "documents", ["organization_id"])


def downgrade() -> None:
    op.drop_index("documents_organization_id_idx", table_name="documents")
    op.drop_table("documents")
    op.execute("DROP TYPE IF EXISTS document_processing_status")
