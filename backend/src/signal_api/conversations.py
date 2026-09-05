import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signal_api.auth import CurrentUser
from signal_api.config import get_settings
from signal_api.database import get_db_session
from signal_api.models import (
    Conversation,
    ConversationMessage,
    ConversationParticipant,
    ConversationParticipantSide,
    ConversationStatus,
    Membership,
)
from signal_api.suggestion_events import events
from signal_api.suggestions import queue_suggestion_run

router = APIRouter(prefix="/conversations", tags=["conversations"])

DatabaseSession = Annotated[Session, Depends(get_db_session)]


class CreateConversationRequest(BaseModel):
    organization_id: uuid.UUID


class ConversationResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    created_by_user_id: uuid.UUID
    status: ConversationStatus
    created_at: datetime


class ConversationListItemResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    status: ConversationStatus
    created_at: datetime


class CreateConversationMessageRequest(BaseModel):
    speaker_label: str = Field(max_length=100)
    side: ConversationParticipantSide
    content: str

    @field_validator("speaker_label", "content")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        stripped_value = value.strip()
        if not stripped_value:
            raise ValueError("Value must not be empty")
        return stripped_value


class ConversationMessageResponse(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    participant_id: uuid.UUID
    speaker_label: str
    side: ConversationParticipantSide
    sequence_number: int
    content: str


class ConversationParticipantResponse(BaseModel):
    id: uuid.UUID
    side: ConversationParticipantSide
    speaker_label: str
    display_name: str | None


class ConversationDetailMessageResponse(BaseModel):
    id: uuid.UUID
    participant_id: uuid.UUID
    speaker_label: str
    side: ConversationParticipantSide
    sequence_number: int
    content: str


class ConversationDetailResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    created_by_user_id: uuid.UUID
    status: ConversationStatus
    created_at: datetime
    participants: list[ConversationParticipantResponse]
    messages: list[ConversationDetailMessageResponse]


@router.post(
    "",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_conversation(
    request: CreateConversationRequest,
    db: DatabaseSession,
    current_user: CurrentUser,
) -> ConversationResponse:
    membership = db.get(
        Membership,
        {
            "organization_id": request.organization_id,
            "user_id": current_user.id,
        },
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this organization",
        )

    conversation = Conversation(
        organization_id=request.organization_id,
        created_by_user_id=current_user.id,
    )
    db.add(conversation)
    db.commit()

    return ConversationResponse(
        id=conversation.id,
        organization_id=conversation.organization_id,
        created_by_user_id=conversation.created_by_user_id,
        status=conversation.status,
        created_at=conversation.created_at,
    )


@router.get("", response_model=list[ConversationListItemResponse])
def list_conversations(
    db: DatabaseSession,
    current_user: CurrentUser,
) -> list[ConversationListItemResponse]:
    conversations = db.scalars(
        select(Conversation)
        .join(
            Membership,
            Membership.organization_id == Conversation.organization_id,
        )
        .where(Membership.user_id == current_user.id)
        .order_by(Conversation.created_at.desc(), Conversation.id.desc())
    ).all()

    return [
        ConversationListItemResponse(
            id=conversation.id,
            organization_id=conversation.organization_id,
            status=conversation.status,
            created_at=conversation.created_at,
        )
        for conversation in conversations
    ]


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
def get_conversation(
    conversation_id: uuid.UUID,
    db: DatabaseSession,
    current_user: CurrentUser,
) -> ConversationDetailResponse:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    membership = db.get(
        Membership,
        {
            "organization_id": conversation.organization_id,
            "user_id": current_user.id,
        },
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this organization",
        )

    participants = db.scalars(
        select(ConversationParticipant)
        .where(ConversationParticipant.conversation_id == conversation.id)
        .order_by(ConversationParticipant.created_at, ConversationParticipant.id)
    ).all()
    message_rows = db.execute(
        select(ConversationMessage, ConversationParticipant)
        .join(
            ConversationParticipant,
            ConversationParticipant.id == ConversationMessage.participant_id,
        )
        .where(ConversationMessage.conversation_id == conversation.id)
        .order_by(ConversationMessage.sequence_number)
    ).all()

    return ConversationDetailResponse(
        id=conversation.id,
        organization_id=conversation.organization_id,
        created_by_user_id=conversation.created_by_user_id,
        status=conversation.status,
        created_at=conversation.created_at,
        participants=[
            ConversationParticipantResponse(
                id=participant.id,
                side=participant.side,
                speaker_label=participant.speaker_label,
                display_name=participant.display_name,
            )
            for participant in participants
        ],
        messages=[
            ConversationDetailMessageResponse(
                id=message.id,
                participant_id=message.participant_id,
                speaker_label=participant.speaker_label,
                side=participant.side,
                sequence_number=message.sequence_number,
                content=message.content,
            )
            for message, participant in message_rows
        ],
    )


@router.post(
    "/{conversation_id}/end",
    response_model=ConversationResponse,
)
def end_conversation(
    conversation_id: uuid.UUID,
    db: DatabaseSession,
    current_user: CurrentUser,
) -> ConversationResponse:
    conversation = db.scalar(
        select(Conversation).where(Conversation.id == conversation_id).with_for_update()
    )
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    membership = db.get(
        Membership,
        {
            "organization_id": conversation.organization_id,
            "user_id": current_user.id,
        },
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this organization",
        )

    if conversation.status is ConversationStatus.ACTIVE:
        conversation.status = ConversationStatus.ENDED
        db.commit()

    return ConversationResponse(
        id=conversation.id,
        organization_id=conversation.organization_id,
        created_by_user_id=conversation.created_by_user_id,
        status=conversation.status,
        created_at=conversation.created_at,
    )


@router.post(
    "/{conversation_id}/messages",
    response_model=ConversationMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_conversation_message(
    conversation_id: uuid.UUID,
    request: CreateConversationMessageRequest,
    db: DatabaseSession,
    current_user: CurrentUser,
) -> ConversationMessageResponse:
    conversation = db.scalar(
        select(Conversation).where(Conversation.id == conversation_id).with_for_update()
    )
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    membership = db.get(
        Membership,
        {
            "organization_id": conversation.organization_id,
            "user_id": current_user.id,
        },
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this organization",
        )

    if conversation.status is ConversationStatus.ENDED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conversation has ended",
        )

    participant = db.scalar(
        select(ConversationParticipant).where(
            ConversationParticipant.conversation_id == conversation_id,
            ConversationParticipant.speaker_label == request.speaker_label,
        )
    )
    if participant is None:
        participant = ConversationParticipant(
            conversation_id=conversation_id,
            speaker_label=request.speaker_label,
            side=request.side,
        )
        db.add(participant)
        db.flush()
    elif participant.side is not request.side:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Speaker label is already assigned to a different side",
        )

    latest_sequence_number = db.scalar(
        select(func.max(ConversationMessage.sequence_number)).where(
            ConversationMessage.conversation_id == conversation_id
        )
    )
    message = ConversationMessage(
        conversation_id=conversation_id,
        participant_id=participant.id,
        sequence_number=(latest_sequence_number or 0) + 1,
        content=request.content,
    )
    db.add(message)
    db.flush()
    run = (
        queue_suggestion_run(db, conversation_id)
        if get_settings().suggestions_enabled
        else None
    )
    db.commit()
    if run:
        events.queued(conversation_id, run.id, run.generation)

    return ConversationMessageResponse(
        id=message.id,
        conversation_id=message.conversation_id,
        participant_id=message.participant_id,
        speaker_label=participant.speaker_label,
        side=participant.side,
        sequence_number=message.sequence_number,
        content=message.content,
    )
