"""add persistent conversation confirmation items

Revision ID: 0013_add_confirmation_items
Revises: 0012_add_handoff_receiving
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0013_add_confirmation_items"
down_revision = "0012_add_handoff_receiving"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_confirmation_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("normalized_content", sa.String(500), nullable=False),
        sa.Column(
            "status", sa.String(16), nullable=False, server_default=sa.text("'open'")
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "origin_message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversation_messages.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "evidence_message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversation_messages.id", ondelete="SET NULL"),
        ),
        sa.Column("confirmation_source", sa.String(16), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "conversation_id",
            "normalized_content",
            name="conversation_confirmation_items_conversation_content_unique",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'confirmed')",
            name="conversation_confirmation_items_status_check",
        ),
        sa.CheckConstraint(
            "version > 0", name="conversation_confirmation_items_version_check"
        ),
    )
    op.create_index(
        "conversation_confirmation_items_conversation_id_idx",
        "conversation_confirmation_items",
        ["conversation_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "conversation_confirmation_items_conversation_id_idx",
        table_name="conversation_confirmation_items",
    )
    op.drop_table("conversation_confirmation_items")
