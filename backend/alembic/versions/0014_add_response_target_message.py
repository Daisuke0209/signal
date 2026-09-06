"""Store the validated customer message targeted by a response suggestion."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0014_add_response_target_message"
down_revision = "0013_add_confirmation_items"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "suggestions",
        sa.Column("customer_message_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "suggestions", sa.Column("customer_message_content", sa.Text(), nullable=True)
    )
    op.create_foreign_key(
        "suggestions_customer_message_id_fk",
        "suggestions",
        "conversation_messages",
        ["customer_message_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "suggestions_customer_message_id_fk", "suggestions", type_="foreignkey"
    )
    op.drop_column("suggestions", "customer_message_content")
    op.drop_column("suggestions", "customer_message_id")
