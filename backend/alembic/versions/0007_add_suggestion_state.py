"""Persist suggestion runs and ordered results.

Revision ID: 0007_add_suggestion_state
Revises: 0006_add_transcription_sessions
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0007_add_suggestion_state"
down_revision = "0006_add_transcription_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "suggestion_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("input_sequence_number", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "succeeded",
                "failed",
                name="suggestion_run_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="queued",
            nullable=False,
        ),
        sa.Column(
            "error_code",
            sa.Enum(
                "provider_unavailable",
                "timeout",
                "generation_failed",
                "interrupted",
                name="suggestion_error_code",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id", "generation", name="suggestion_runs_generation_unique"
        ),
        sa.CheckConstraint(
            "generation > 0", name="suggestion_runs_generation_positive"
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id", "input_sequence_number"],
            [
                "conversation_messages.conversation_id",
                "conversation_messages.sequence_number",
            ],
            name="suggestion_runs_input_message_fk",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "(status IN ('queued', 'running') AND completed_at IS NULL "
            "AND error_code IS NULL) "
            "OR (status = 'succeeded' AND completed_at IS NOT NULL "
            "AND error_code IS NULL) "
            "OR (status = 'failed' AND completed_at IS NOT NULL "
            "AND error_code IS NOT NULL)",
            name="suggestion_runs_terminal_state_check",
        ),
    )
    op.create_table(
        "suggestions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "question",
                "response",
                "confirmation",
                name="suggestion_kind",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["run_id"], ["suggestion_runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "run_id", "position", name="suggestions_run_position_unique"
        ),
        sa.CheckConstraint("position >= 0", name="suggestions_position_nonnegative"),
        sa.CheckConstraint(
            "length(btrim(content)) > 0 AND length(content) <= 4000",
            name="suggestions_content_length_check",
        ),
    )


def downgrade() -> None:
    op.drop_table("suggestions")
    op.drop_table("suggestion_runs")
