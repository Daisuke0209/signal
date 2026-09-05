"""add transcription sessions

Revision ID: 0006_add_transcription_sessions
Revises: 0005_add_document_pages
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0006_add_transcription_sessions"
down_revision = "0005_add_document_pages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "transcription_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "transcription_items",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_id", sa.String(255), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["session_id"], ["transcription_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["message_id"], ["conversation_messages.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("session_id", "item_id"),
    )


def downgrade() -> None:
    op.drop_table("transcription_items")
    op.drop_table("transcription_sessions")
