"""Create the authentication foundation schema.

Revision ID: 0001_python_baseline
Revises:
Create Date: 2026-09-03
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001_python_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # IF NOT EXISTS lets an existing Drizzle-managed development database adopt
    # this baseline without dropping its compatible tables or data.
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE membership_role AS ENUM ('rep', 'manager', 'admin');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS organizations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
            name varchar(255) NOT NULL,
            slug varchar(100) NOT NULL,
            created_at timestamp with time zone DEFAULT now() NOT NULL,
            CONSTRAINT organizations_slug_unique UNIQUE (slug)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
            name varchar(255) NOT NULL,
            email varchar(320) NOT NULL,
            password_hash text NOT NULL,
            created_at timestamp with time zone DEFAULT now() NOT NULL,
            CONSTRAINT users_email_unique UNIQUE (email)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS memberships (
            organization_id uuid NOT NULL,
            user_id uuid NOT NULL,
            role membership_role DEFAULT 'rep' NOT NULL,
            created_at timestamp with time zone DEFAULT now() NOT NULL,
            CONSTRAINT memberships_organization_id_user_id_pk
                PRIMARY KEY (organization_id, user_id),
            CONSTRAINT memberships_organization_id_organizations_id_fk
                FOREIGN KEY (organization_id) REFERENCES organizations (id)
                ON DELETE CASCADE,
            CONSTRAINT memberships_user_id_users_id_fk
                FOREIGN KEY (user_id) REFERENCES users (id)
                ON DELETE CASCADE
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
            user_id uuid NOT NULL,
            token_hash varchar(64) NOT NULL,
            expires_at timestamp with time zone NOT NULL,
            created_at timestamp with time zone DEFAULT now() NOT NULL,
            CONSTRAINT sessions_token_hash_unique UNIQUE (token_hash),
            CONSTRAINT sessions_user_id_users_id_fk
                FOREIGN KEY (user_id) REFERENCES users (id)
                ON DELETE CASCADE
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS memberships_user_id_idx ON memberships (user_id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS sessions_user_id_idx ON sessions (user_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS sessions_expires_at_idx ON sessions (expires_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sessions")
    op.execute("DROP TABLE IF EXISTS memberships")
    op.execute("DROP TABLE IF EXISTS users")
    op.execute("DROP TABLE IF EXISTS organizations")
    op.execute("DROP TYPE IF EXISTS membership_role")
