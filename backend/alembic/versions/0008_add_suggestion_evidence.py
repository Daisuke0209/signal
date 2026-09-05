"""Store suggestion evidence snapshots and streamed state revisions."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0008_add_suggestion_evidence"
down_revision = "0007_add_suggestion_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "suggestion_runs",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("suggestion_runs", sa.Column("phase", sa.String(16), nullable=True))
    op.create_check_constraint(
        "suggestion_runs_revision_check", "suggestion_runs", "revision >= 0"
    )
    op.create_check_constraint(
        "suggestion_runs_phase_check",
        "suggestion_runs",
        "phase IS NULL OR (status = 'running' AND "
        "phase IN ('generating', 'searching'))",
    )
    op.add_column(
        "suggestions",
        sa.Column(
            "sources",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_check_constraint(
        "suggestions_sources_check", "suggestions", "jsonb_typeof(sources) = 'array'"
    )


def downgrade() -> None:
    op.drop_constraint("suggestions_sources_check", "suggestions")
    op.drop_column("suggestions", "sources")
    op.drop_constraint("suggestion_runs_phase_check", "suggestion_runs")
    op.drop_constraint("suggestion_runs_revision_check", "suggestion_runs")
    op.drop_column("suggestion_runs", "phase")
    op.drop_column("suggestion_runs", "revision")
