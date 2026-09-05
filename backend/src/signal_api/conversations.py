import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from signal_api.auth import CurrentUser
from signal_api.database import get_db_session
from signal_api.models import (
    Conversation,
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
