"""Add the text conversation schema.

Revision ID: 0002_add_conversation_schema
Revises: 0001_python_baseline
Create Date: 2026-09-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_add_conversation_schema"
down_revision: str | None = "0001_python_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


conversation_status = postgresql.ENUM(
    "active",
    "ended",
    name="conversation_status",
    create_type=False,
)
conversation_participant_side = postgresql.ENUM(
    "customer",
    "sales_rep",
    name="conversation_participant_side",
    create_type=False,
)


def upgrade() -> None:
    conversation_status.create(op.get_bind(), checkfirst=True)
    conversation_participant_side.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "conversations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            conversation_status,
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="conversations_created_by_user_id_users_id_fk",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="conversations_organization_id_organizations_id_fk",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "conversations_created_by_user_id_idx",
        "conversations",
        ["created_by_user_id"],
    )
    op.create_index(
        "conversations_organization_id_idx",
        "conversations",
        ["organization_id"],
    )

    op.create_table(
        "conversation_participants",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("side", conversation_participant_side, nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="conversation_participants_conversation_id_conversations_id_fk",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id",
            "id",
            name="conversation_participants_conversation_id_id_unique",
        ),
    )
    op.create_index(
        "conversation_participants_conversation_id_idx",
        "conversation_participants",
        ["conversation_id"],
    )

    op.create_table(
        "conversation_messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("participant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "sequence_number > 0",
            name="conversation_messages_sequence_number_positive",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id", "participant_id"],
            [
                "conversation_participants.conversation_id",
                "conversation_participants.id",
            ],
            name="conversation_messages_participant_fk",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id",
            "sequence_number",
            name="conversation_messages_conversation_id_sequence_number_unique",
        ),
    )


def downgrade() -> None:
    op.drop_table("conversation_messages")
    op.drop_index(
        "conversation_participants_conversation_id_idx",
        table_name="conversation_participants",
    )
    op.drop_table("conversation_participants")
    op.drop_index("conversations_organization_id_idx", table_name="conversations")
    op.drop_index("conversations_created_by_user_id_idx", table_name="conversations")
    op.drop_table("conversations")

    conversation_participant_side.drop(op.get_bind(), checkfirst=True)
    conversation_status.drop(op.get_bind(), checkfirst=True)
