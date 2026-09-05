import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Organization(Base):
    __tablename__ = "organizations"
    __table_args__ = (UniqueConstraint("slug", name="organizations_slug_unique"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="users_email_unique"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class UserSession(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint("token_hash", name="sessions_token_hash_unique"),
        Index("sessions_user_id_idx", "user_id"),
        Index("sessions_expires_at_idx", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            name="sessions_user_id_users_id_fk",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class MembershipRole(StrEnum):
    REP = "rep"
    MANAGER = "manager"
    ADMIN = "admin"


membership_role_type = Enum(
    MembershipRole,
    name="membership_role",
    values_callable=lambda members: [member.value for member in members],
)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        PrimaryKeyConstraint(
            "organization_id",
            "user_id",
            name="memberships_organization_id_user_id_pk",
        ),
        Index("memberships_user_id_idx", "user_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "organizations.id",
            name="memberships_organization_id_organizations_id_fk",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            name="memberships_user_id_users_id_fk",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    role: Mapped[MembershipRole] = mapped_column(
        membership_role_type,
        nullable=False,
        server_default=text("'rep'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ConversationStatus(StrEnum):
    ACTIVE = "active"
    ENDED = "ended"


conversation_status_type = Enum(
    ConversationStatus,
    name="conversation_status",
    values_callable=lambda members: [member.value for member in members],
)


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("conversations_organization_id_idx", "organization_id"),
        Index("conversations_created_by_user_id_idx", "created_by_user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "organizations.id",
            name="conversations_organization_id_organizations_id_fk",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            name="conversations_created_by_user_id_users_id_fk",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    status: Mapped[ConversationStatus] = mapped_column(
        conversation_status_type,
        nullable=False,
        server_default=text("'active'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ConversationParticipantSide(StrEnum):
    CUSTOMER = "customer"
    SALES_REP = "sales_rep"


conversation_participant_side_type = Enum(
    ConversationParticipantSide,
    name="conversation_participant_side",
    values_callable=lambda members: [member.value for member in members],
)


class ConversationParticipant(Base):
    __tablename__ = "conversation_participants"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "id",
            name="conversation_participants_conversation_id_id_unique",
        ),
        Index("conversation_participants_conversation_id_idx", "conversation_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "conversations.id",
            name="conversation_participants_conversation_id_conversations_id_fk",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    side: Mapped[ConversationParticipantSide] = mapped_column(
        conversation_participant_side_type,
        nullable=False,
    )
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "sequence_number",
            name="conversation_messages_conversation_id_sequence_number_unique",
        ),
        CheckConstraint(
            "sequence_number > 0",
            name="conversation_messages_sequence_number_positive",
        ),
        ForeignKeyConstraint(
            ["conversation_id", "participant_id"],
            [
                "conversation_participants.conversation_id",
                "conversation_participants.id",
            ],
            name="conversation_messages_participant_fk",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    participant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
