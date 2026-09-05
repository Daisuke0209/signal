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
from sqlalchemy.dialects.postgresql import JSONB, UUID
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


class ApprovalRequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


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
        UniqueConstraint(
            "conversation_id",
            "speaker_label",
            name="conversation_participants_conversation_id_speaker_label_unique",
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
    speaker_label: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
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


class ConversationDocument(Base):
    __tablename__ = "conversation_documents"
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TranscriptionSession(Base):
    __tablename__ = "transcription_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'active'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TranscriptionItem(Base):
    __tablename__ = "transcription_items"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("transcription_sessions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    item_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversation_messages.id", ondelete="CASCADE"),
        nullable=True,
    )


class DocumentProcessingStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    TEXT_UNAVAILABLE = "text_unavailable"


document_processing_status_type = Enum(
    DocumentProcessingStatus,
    name="document_processing_status",
    values_callable=lambda members: [member.value for member in members],
)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (Index("documents_organization_id_idx", "organization_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "organizations.id",
            name="documents_organization_id_organizations_id_fk",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    uploaded_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            name="documents_uploaded_by_user_id_users_id_fk",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    processing_status: Mapped[DocumentProcessingStatus] = mapped_column(
        document_processing_status_type,
        nullable=False,
        server_default=text("'pending'"),
    )
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SuggestionRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class SuggestionKind(StrEnum):
    QUESTION = "question"
    RESPONSE = "response"
    CONFIRMATION = "confirmation"


class SuggestionErrorCode(StrEnum):
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    TIMEOUT = "timeout"
    GENERATION_FAILED = "generation_failed"
    INTERRUPTED = "interrupted"


class SuggestionRun(Base):
    __tablename__ = "suggestion_runs"
    __table_args__ = (
        CheckConstraint("revision >= 0", name="suggestion_runs_revision_check"),
        CheckConstraint(
            "phase IS NULL OR (status = 'running' AND "
            "phase IN ('generating', 'searching'))",
            name="suggestion_runs_phase_check",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="suggestion_run_status",
        ),
        CheckConstraint(
            "error_code IN ('provider_unavailable', 'timeout', "
            "'generation_failed', 'interrupted')",
            name="suggestion_error_code",
        ),
        UniqueConstraint(
            "conversation_id", "generation", name="suggestion_runs_generation_unique"
        ),
        CheckConstraint("generation > 0", name="suggestion_runs_generation_positive"),
        ForeignKeyConstraint(
            ["conversation_id", "input_sequence_number"],
            [
                "conversation_messages.conversation_id",
                "conversation_messages.sequence_number",
            ],
            name="suggestion_runs_input_message_fk",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "(status IN ('queued', 'running') AND completed_at IS NULL "
            "AND error_code IS NULL) "
            "OR (status = 'succeeded' AND completed_at IS NOT NULL "
            "AND error_code IS NULL) "
            "OR (status = 'failed' AND completed_at IS NOT NULL "
            "AND error_code IS NOT NULL)",
            name="suggestion_runs_terminal_state_check",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    phase: Mapped[str | None] = mapped_column(String(16), nullable=True)
    input_sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[SuggestionRunStatus] = mapped_column(
        Enum(
            SuggestionRunStatus,
            values_callable=lambda members: [m.value for m in members],
            name="suggestion_run_status",
            native_enum=False,
            create_constraint=False,
        ),
        nullable=False,
        server_default="queued",
    )
    error_code: Mapped[SuggestionErrorCode | None] = mapped_column(
        Enum(
            SuggestionErrorCode,
            values_callable=lambda members: [m.value for m in members],
            name="suggestion_error_code",
            native_enum=False,
            create_constraint=False,
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Suggestion(Base):
    __tablename__ = "suggestions"
    __table_args__ = (
        CheckConstraint(
            "jsonb_typeof(sources) = 'array'", name="suggestions_sources_check"
        ),
        CheckConstraint(
            "kind IN ('question', 'response', 'confirmation')",
            name="suggestion_kind",
        ),
        UniqueConstraint("run_id", "position", name="suggestions_run_position_unique"),
        CheckConstraint("position >= 0", name="suggestions_position_nonnegative"),
        CheckConstraint(
            "length(btrim(content)) > 0 AND length(content) <= 4000",
            name="suggestions_content_length_check",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("suggestion_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[SuggestionKind] = mapped_column(
        Enum(
            SuggestionKind,
            values_callable=lambda members: [m.value for m in members],
            name="suggestion_kind",
            native_enum=False,
            create_constraint=False,
        ),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sources: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )


class DocumentPage(Base):
    __tablename__ = "document_pages"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "page_number",
            name="document_pages_document_id_page_number_unique",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="approval_requests_status_check",
        ),
        Index("approval_requests_conversation_id_idx", "conversation_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    operation: Mapped[str] = mapped_column(String(100), nullable=False)
    target: Mapped[str] = mapped_column(String(255), nullable=False)
    input: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    evidence: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    status: Mapped[ApprovalRequestStatus] = mapped_column(
        Enum(
            ApprovalRequestStatus,
            values_callable=lambda members: [m.value for m in members],
            name="approval_request_status",
            length=20,
            native_enum=False,
            create_constraint=False,
        ),
        nullable=False,
        server_default=text("'pending'"),
    )
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class InternalHandoff(Base):
    __tablename__ = "internal_handoffs"
    approval_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("approval_requests.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ConversationSummary(Base):
    __tablename__ = "conversation_summaries"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'generating', 'succeeded', 'failed')",
            name="conversation_summaries_status_check",
        ),
        CheckConstraint("attempt >= 1", name="conversation_summaries_attempt_check"),
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    result: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
