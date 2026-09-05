"""add handoff receiving state

Revision ID: 0012_add_handoff_receiving
Revises: 0011_add_conversation_summaries
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0012_add_handoff_receiving"
down_revision = "0011_add_conversation_summaries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "internal_handoffs",
        sa.Column(
            "status", sa.String(20), server_default=sa.text("'open'"), nullable=False
        ),
    )
    op.add_column(
        "internal_handoffs",
        sa.Column("assignee_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "internal_handoffs",
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "internal_handoffs", sa.Column("response_content", sa.Text(), nullable=True)
    )
    op.add_column(
        "internal_handoffs",
        sa.Column("responded_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "internal_handoffs",
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "internal_handoffs",
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "internal_handoffs_assignee_user_id_users_id_fk",
        "internal_handoffs",
        "users",
        ["assignee_user_id"],
        ["id"],
    )
    op.create_foreign_key(
        "internal_handoffs_responded_by_user_id_users_id_fk",
        "internal_handoffs",
        "users",
        ["responded_by_user_id"],
        ["id"],
    )
    op.create_check_constraint(
        "internal_handoffs_state_check",
        "internal_handoffs",
        "(status = 'open' AND assignee_user_id IS NULL "
        "AND response_content IS NULL) "
        "OR (status = 'claimed' AND assignee_user_id IS NOT NULL "
        "AND response_content IS NULL) "
        "OR (status = 'resolved' AND assignee_user_id IS NOT NULL "
        "AND response_content IS NOT NULL)",
    )
    op.create_index(
        "internal_handoffs_status_assignee_idx",
        "internal_handoffs",
        ["status", "assignee_user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "internal_handoffs_status_assignee_idx", table_name="internal_handoffs"
    )
    op.drop_constraint(
        "internal_handoffs_state_check", "internal_handoffs", type_="check"
    )
    op.drop_constraint(
        "internal_handoffs_responded_by_user_id_users_id_fk",
        "internal_handoffs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "internal_handoffs_assignee_user_id_users_id_fk",
        "internal_handoffs",
        type_="foreignkey",
    )
    op.drop_column("internal_handoffs", "resolved_at")
    op.drop_column("internal_handoffs", "responded_at")
    op.drop_column("internal_handoffs", "responded_by_user_id")
    op.drop_column("internal_handoffs", "response_content")
    op.drop_column("internal_handoffs", "claimed_at")
    op.drop_column("internal_handoffs", "assignee_user_id")
    op.drop_column("internal_handoffs", "status")
