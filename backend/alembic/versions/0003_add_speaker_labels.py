"""Add stable speaker labels and make participant names optional.

Revision ID: 0003_speaker_labels
Revises: 0002_add_conversation_schema
Create Date: 2026-09-05
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_speaker_labels"
down_revision: str | None = "0002_add_conversation_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversation_participants",
        sa.Column("speaker_label", sa.String(length=100), nullable=True),
    )
    op.execute(
        """
        WITH ranked_participants AS (
            SELECT
                id,
                'speaker_' || row_number() OVER (
                    PARTITION BY conversation_id
                    ORDER BY created_at, id
                ) AS speaker_label
            FROM conversation_participants
        )
        UPDATE conversation_participants AS participant
        SET speaker_label = ranked.speaker_label
        FROM ranked_participants AS ranked
        WHERE participant.id = ranked.id
        """
    )
    op.alter_column("conversation_participants", "speaker_label", nullable=False)
    op.alter_column("conversation_participants", "display_name", nullable=True)
    op.create_unique_constraint(
        "conversation_participants_conversation_id_speaker_label_unique",
        "conversation_participants",
        ["conversation_id", "speaker_label"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "conversation_participants_conversation_id_speaker_label_unique",
        "conversation_participants",
        type_="unique",
    )
    op.execute(
        """
        UPDATE conversation_participants
        SET display_name = speaker_label
        WHERE display_name IS NULL
        """
    )
    op.alter_column("conversation_participants", "display_name", nullable=False)
    op.drop_column("conversation_participants", "speaker_label")
