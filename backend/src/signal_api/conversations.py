import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signal_api.auth import CurrentUser
from signal_api.database import get_db_session
from signal_api.models import (
    Conversation,
    ConversationMessage,
    ConversationParticipant,
    ConversationParticipantSide,
    ConversationStatus,
    Membership,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])

DatabaseSession = Annotated[Session, Depends(get_db_session)]


class CreateConversationRequest(BaseModel):
    organization_id: uuid.UUID


class ConversationResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    created_by_user_id: uuid.UUID
    status: ConversationStatus


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
    db.commit()

    return ConversationMessageResponse(
        id=message.id,
        conversation_id=message.conversation_id,
        participant_id=message.participant_id,
        speaker_label=participant.speaker_label,
        side=participant.side,
        sequence_number=message.sequence_number,
        content=message.content,
    )
