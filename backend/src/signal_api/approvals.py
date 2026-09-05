import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from signal_api.auth import CurrentUser
from signal_api.database import get_db_session
from signal_api.models import (
    ApprovalRequest,
    ApprovalRequestStatus,
    Conversation,
    InternalHandoff,
    Membership,
)

router = APIRouter(prefix="/conversations", tags=["approvals"])
DatabaseSession = Annotated[Session, Depends(get_db_session)]


class InternalHandoffInput(BaseModel):
    summary: str = Field(min_length=1, max_length=4000)


class ApprovalEvidence(BaseModel):
    document_id: uuid.UUID
    document_name: str = Field(min_length=1, max_length=255)
    page_number: int = Field(ge=1)
    excerpt: str = Field(min_length=1, max_length=2000)


class ApprovalCreate(BaseModel):
    operation: Literal["internal_handoff"]
    target: str = Field(min_length=1, max_length=255)
    input: InternalHandoffInput
    evidence: list[ApprovalEvidence] = Field(default_factory=list, max_length=10)


class ApprovalResponse(ApprovalCreate):
    id: uuid.UUID
    conversation_id: uuid.UUID
    status: ApprovalRequestStatus
    requested_by_user_id: uuid.UUID
    decided_by_user_id: uuid.UUID | None
    decided_at: datetime | None
    created_at: datetime


def authorized_conversation(
    db: Session, cid: uuid.UUID, user_id: uuid.UUID
) -> Conversation:
    conversation = db.get(Conversation, cid)
    if conversation is None:
        raise HTTPException(404, "Conversation not found")
    if (
        db.get(
            Membership,
            {"organization_id": conversation.organization_id, "user_id": user_id},
        )
        is None
    ):
        raise HTTPException(403, "Not a member of this organization")
    return conversation


def response(item: ApprovalRequest) -> ApprovalResponse:
    return ApprovalResponse.model_validate(item, from_attributes=True)


@router.post(
    "/{conversation_id}/approvals",
    response_model=ApprovalResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_approval(
    conversation_id: uuid.UUID,
    request: ApprovalCreate,
    db: DatabaseSession,
    current_user: CurrentUser,
) -> ApprovalResponse:
    authorized_conversation(db, conversation_id, current_user.id)
    item = ApprovalRequest(
        conversation_id=conversation_id,
        requested_by_user_id=current_user.id,
        **request.model_dump(mode="json"),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return response(item)


@router.get("/{conversation_id}/approvals", response_model=list[ApprovalResponse])
def list_approvals(
    conversation_id: uuid.UUID, db: DatabaseSession, current_user: CurrentUser
) -> list[ApprovalResponse]:
    authorized_conversation(db, conversation_id, current_user.id)
    return [
        response(item)
        for item in db.scalars(
            select(ApprovalRequest)
            .where(ApprovalRequest.conversation_id == conversation_id)
            .order_by(ApprovalRequest.created_at)
        ).all()
    ]


def decide(
    approval_id: uuid.UUID,
    desired: ApprovalRequestStatus,
    db: Session,
    user_id: uuid.UUID,
) -> ApprovalRequest:
    item = db.scalar(
        select(ApprovalRequest)
        .where(ApprovalRequest.id == approval_id)
        .with_for_update()
    )
    if item is None:
        raise HTTPException(404, "Approval request not found")
    authorized_conversation(db, item.conversation_id, user_id)
    if item.status is not ApprovalRequestStatus.PENDING:
        if item.status is desired:
            return item
        raise HTTPException(
            status_code=409, detail="Approval request is already decided"
        )
    item.status = desired
    item.decided_by_user_id = user_id
    item.decided_at = datetime.now(UTC)
    if desired is ApprovalRequestStatus.APPROVED:
        db.add(InternalHandoff(approval_request_id=item.id))
    db.commit()
    db.refresh(item)
    return item


@router.post("/approvals/{approval_id}/approve", response_model=ApprovalResponse)
def approve(
    approval_id: uuid.UUID, db: DatabaseSession, current_user: CurrentUser
) -> ApprovalResponse:
    return response(
        decide(approval_id, ApprovalRequestStatus.APPROVED, db, current_user.id)
    )


@router.post("/approvals/{approval_id}/reject", response_model=ApprovalResponse)
def reject(
    approval_id: uuid.UUID, db: DatabaseSession, current_user: CurrentUser
) -> ApprovalResponse:
    return response(
        decide(approval_id, ApprovalRequestStatus.REJECTED, db, current_user.id)
    )
