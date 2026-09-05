import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from signal_api.approvals import authorized_conversation
from signal_api.auth import CurrentUser
from signal_api.database import get_db_session
from signal_api.models import (
    ApprovalRequest,
    Conversation,
    InternalHandoff,
    InternalHandoffStatus,
    Membership,
)

router = APIRouter(tags=["handoffs"])
DatabaseSession = Annotated[Session, Depends(get_db_session)]


class HandoffEvidence(BaseModel):
    document_id: uuid.UUID
    document_name: str
    page_number: int
    excerpt: str


class HandoffResponse(BaseModel):
    approval_request_id: uuid.UUID
    conversation_id: uuid.UUID
    target: str
    summary: str
    evidence: list[HandoffEvidence]
    requested_by_user_id: uuid.UUID
    created_at: datetime
    status: InternalHandoffStatus
    assignee_user_id: uuid.UUID | None
    claimed_at: datetime | None
    response_content: str | None
    responded_by_user_id: uuid.UUID | None
    responded_at: datetime | None
    resolved_at: datetime | None


class HandoffResponseRequest(BaseModel):
    content: str = Field(max_length=4000)

    @field_validator("content")
    @classmethod
    def non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Value must not be empty")
        return value


def handoff_response(
    handoff: InternalHandoff, approval: ApprovalRequest
) -> HandoffResponse:
    return HandoffResponse(
        approval_request_id=handoff.approval_request_id,
        conversation_id=approval.conversation_id,
        target=approval.target,
        summary=str(approval.input["summary"]),
        evidence=[HandoffEvidence.model_validate(item) for item in approval.evidence],
        requested_by_user_id=approval.requested_by_user_id,
        created_at=handoff.created_at,
        status=handoff.status,
        assignee_user_id=handoff.assignee_user_id,
        claimed_at=handoff.claimed_at,
        response_content=handoff.response_content,
        responded_by_user_id=handoff.responded_by_user_id,
        responded_at=handoff.responded_at,
        resolved_at=handoff.resolved_at,
    )


def handoff_row(
    db: Session, approval_id: uuid.UUID, user_id: uuid.UUID, *, lock: bool = False
) -> tuple[InternalHandoff, ApprovalRequest]:
    statement = (
        select(InternalHandoff, ApprovalRequest, Conversation)
        .join(
            ApprovalRequest, ApprovalRequest.id == InternalHandoff.approval_request_id
        )
        .join(Conversation, Conversation.id == ApprovalRequest.conversation_id)
        .where(InternalHandoff.approval_request_id == approval_id)
    )
    row = db.execute(statement.with_for_update() if lock else statement).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Handoff not found")
    handoff, approval, conversation = row
    if (
        db.get(
            Membership,
            {"organization_id": conversation.organization_id, "user_id": user_id},
        )
        is None
    ):
        raise HTTPException(status_code=403, detail="Not a member of this organization")
    return handoff, approval


@router.get("/handoffs", response_model=list[HandoffResponse])
def list_handoffs(
    db: DatabaseSession, current_user: CurrentUser
) -> list[HandoffResponse]:
    rows = db.execute(
        select(InternalHandoff, ApprovalRequest)
        .join(
            ApprovalRequest, ApprovalRequest.id == InternalHandoff.approval_request_id
        )
        .join(Conversation, Conversation.id == ApprovalRequest.conversation_id)
        .join(Membership, Membership.organization_id == Conversation.organization_id)
        .where(Membership.user_id == current_user.id)
        .where(
            or_(
                InternalHandoff.status == InternalHandoffStatus.OPEN,
                InternalHandoff.assignee_user_id == current_user.id,
            )
        )
        .order_by(InternalHandoff.created_at.desc())
    ).all()
    return [handoff_response(handoff, approval) for handoff, approval in rows]


@router.get("/handoffs/{approval_id}", response_model=HandoffResponse)
def get_handoff(
    approval_id: uuid.UUID, db: DatabaseSession, current_user: CurrentUser
) -> HandoffResponse:
    handoff, approval = handoff_row(db, approval_id, current_user.id)
    return handoff_response(handoff, approval)


@router.post("/handoffs/{approval_id}/claim", response_model=HandoffResponse)
def claim_handoff(
    approval_id: uuid.UUID, db: DatabaseSession, current_user: CurrentUser
) -> HandoffResponse:
    handoff, approval = handoff_row(db, approval_id, current_user.id, lock=True)
    if handoff.status is InternalHandoffStatus.OPEN:
        handoff.status = InternalHandoffStatus.CLAIMED
        handoff.assignee_user_id = current_user.id
        handoff.claimed_at = datetime.now(UTC)
        db.commit()
        db.refresh(handoff)
        return handoff_response(handoff, approval)
    if (
        handoff.status is InternalHandoffStatus.CLAIMED
        and handoff.assignee_user_id == current_user.id
    ):
        return handoff_response(handoff, approval)
    raise HTTPException(status_code=409, detail="Handoff is not available")


@router.post("/handoffs/{approval_id}/respond", response_model=HandoffResponse)
def respond_to_handoff(
    approval_id: uuid.UUID,
    request: HandoffResponseRequest,
    db: DatabaseSession,
    current_user: CurrentUser,
) -> HandoffResponse:
    handoff, approval = handoff_row(db, approval_id, current_user.id, lock=True)
    if handoff.status is InternalHandoffStatus.RESOLVED:
        raise HTTPException(status_code=409, detail="Handoff is already resolved")
    if (
        handoff.status is not InternalHandoffStatus.CLAIMED
        or handoff.assignee_user_id != current_user.id
    ):
        raise HTTPException(status_code=409, detail="Handoff is not claimed by you")
    now = datetime.now(UTC)
    handoff.status = InternalHandoffStatus.RESOLVED
    handoff.response_content = request.content
    handoff.responded_by_user_id = current_user.id
    handoff.responded_at = now
    handoff.resolved_at = now
    db.commit()
    db.refresh(handoff)
    return handoff_response(handoff, approval)


@router.get(
    "/conversations/{conversation_id}/handoffs", response_model=list[HandoffResponse]
)
def list_conversation_handoffs(
    conversation_id: uuid.UUID, db: DatabaseSession, current_user: CurrentUser
) -> list[HandoffResponse]:
    authorized_conversation(db, conversation_id, current_user.id)
    rows = db.execute(
        select(InternalHandoff, ApprovalRequest)
        .join(
            ApprovalRequest, ApprovalRequest.id == InternalHandoff.approval_request_id
        )
        .where(ApprovalRequest.conversation_id == conversation_id)
        .order_by(InternalHandoff.created_at)
    ).all()
    return [handoff_response(handoff, approval) for handoff, approval in rows]
