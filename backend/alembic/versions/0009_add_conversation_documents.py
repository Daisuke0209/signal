"""Store document selections for a conversation."""

import sqlalchemy as sa

from alembic import op

revision = "0009_add_conversation_documents"
down_revision = "0008_add_suggestion_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_documents",
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("conversation_id", "document_id"),
    )


def downgrade() -> None:
    op.drop_table("conversation_documents")
