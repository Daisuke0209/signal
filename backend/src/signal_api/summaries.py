"""Durable end-of-meeting results with idempotent start and explicit retry."""

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from signal_api.auth import CurrentUser
from signal_api.config import get_settings
from signal_api.database import SessionLocal, get_db_session
from signal_api.domain_traces import span, trace, trace_context
from signal_api.models import (
    Conversation,
    ConversationMessage,
    ConversationParticipant,
    ConversationStatus,
    ConversationSummary,
    Membership,
)
from signal_api.summary_generator import (
    MeetingSummary,
    SummaryFailure,
    generate_summary,
)

router = APIRouter(prefix="/conversations", tags=["summaries"])
DatabaseSession = Annotated[Session, Depends(get_db_session)]


class SummaryState(BaseModel):
    conversation_id: uuid.UUID
    status: str
    attempt: int
    result: MeetingSummary | None
    error_code: str | None
    message_count: int
    created_at: datetime
    completed_at: datetime | None


def serialize(item: ConversationSummary) -> SummaryState:
    return SummaryState.model_validate(item, from_attributes=True)


def authorized(
    db: Session, cid: uuid.UUID, uid: uuid.UUID, *, lock: bool = False
) -> Conversation:
    query = select(Conversation).where(Conversation.id == cid)
    conversation = db.scalar(query.with_for_update() if lock else query)
    if conversation is None:
        raise HTTPException(404, "Conversation not found")
    if (
        db.get(
            Membership,
            {"organization_id": conversation.organization_id, "user_id": uid},
        )
        is None
    ):
        raise HTTPException(403, "Not a member of this organization")
    return conversation


@router.get("/{conversation_id}/summary", response_model=SummaryState | None)
def get_summary(
    conversation_id: uuid.UUID, current_user: CurrentUser, db: DatabaseSession
) -> SummaryState | None:
    authorized(db, conversation_id, current_user.id)
    item = db.get(ConversationSummary, conversation_id)
    return serialize(item) if item else None


@router.post("/{conversation_id}/summary", response_model=SummaryState)
def start_summary(
    conversation_id: uuid.UUID,
    current_user: CurrentUser,
    db: DatabaseSession,
    background_tasks: BackgroundTasks,
    request: Request,
) -> SummaryState:
    conversation = authorized(db, conversation_id, current_user.id, lock=True)
    if conversation.status is not ConversationStatus.ENDED:
        raise HTTPException(409, "End the conversation before generating a summary")
    item = db.get(ConversationSummary, conversation_id)
    if item and item.status != "failed":
        return serialize(item)
    if not get_settings().suggestions_enabled:
        raise HTTPException(503, "AI generation is disabled")
    total_characters = (
        db.scalar(
            select(func.sum(func.length(ConversationMessage.content))).where(
                ConversationMessage.conversation_id == conversation_id
            )
        )
        or 0
    )
    if total_characters > 160_000:
        raise HTTPException(
            413, "This conversation is too long to summarize in one request"
        )
    rows = db.execute(
        select(ConversationMessage.content, ConversationParticipant.side)
        .join(
            ConversationParticipant,
            ConversationParticipant.id == ConversationMessage.participant_id,
        )
        .where(ConversationMessage.conversation_id == conversation_id)
        .order_by(ConversationMessage.sequence_number)
    ).all()
    if not rows:
        raise HTTPException(422, "The conversation has no finalized messages")
    transcript = json.dumps(
        [{"side": side.value, "text": content} for content, side in rows],
        ensure_ascii=False,
    )
    if len(transcript) > 160_000:
        raise HTTPException(
            413, "This conversation is too long to summarize in one request"
        )
    if item is None:
        item = ConversationSummary(
            conversation_id=conversation_id,
            status="queued",
            attempt=1,
            message_count=len(rows),
        )
        db.add(item)
    else:
        item.status, item.error_code, item.completed_at = "queued", None, None
        item.attempt += 1
    db.commit()
    db.refresh(item)
    background_tasks.add_task(
        request.app.state.summary_worker.run, conversation_id, item.attempt, transcript
    )
    return serialize(item)


def set_state(
    cid: uuid.UUID,
    attempt: int,
    expected: str,
    status: str,
    result: MeetingSummary | None = None,
    error_code: str | None = None,
) -> bool:
    with SessionLocal() as db:
        item = db.scalar(
            select(ConversationSummary)
            .where(ConversationSummary.conversation_id == cid)
            .with_for_update()
        )
        if item is None or item.attempt != attempt or item.status != expected:
            return False
        item.status = status
        item.error_code = error_code
        item.result = result.model_dump() if result else None
        if status in {"succeeded", "failed"}:
            item.completed_at = datetime.now(UTC)
        db.commit()
        with trace_context(cid, generation=attempt):
            trace(
                "summary." + status,
                outcome="failed" if status == "failed" else "complete",
                error_code=error_code,
                retryable=status == "failed",
            )
        return True


async def run_summary(cid: uuid.UUID, attempt: int, transcript: str) -> None:
    if not await asyncio.to_thread(set_state, cid, attempt, "queued", "generating"):
        return
    try:
        async with asyncio.timeout(50):
            result = await generate_summary(transcript)
        await asyncio.to_thread(
            set_state, cid, attempt, "generating", "succeeded", result
        )
    except BaseException as error:
        if isinstance(error, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
            code = "interrupted"
        elif isinstance(error, (TimeoutError, SummaryFailure)):
            code = error.code if isinstance(error, SummaryFailure) else "timeout"
        else:
            code = "generation_failed"
        await asyncio.shield(
            asyncio.to_thread(
                set_state, cid, attempt, "generating", "failed", None, code
            )
        )
        if isinstance(error, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
            raise


def recover_summaries() -> None:
    # Single-process deployment: an unfinished provider call cannot survive restart.
    with SessionLocal() as db:
        db.execute(
            update(ConversationSummary)
            .where(ConversationSummary.status.in_(["queued", "generating"]))
            .values(
                status="failed",
                error_code="interrupted",
                completed_at=datetime.now(UTC),
            )
        )
        db.commit()


class SummaryWorker:
    def __init__(self) -> None:
        self.capacity = asyncio.Semaphore(2)

    async def run(self, cid: uuid.UUID, attempt: int, transcript: str) -> None:
        with trace_context(cid, generation=attempt):
            async with self.capacity:
                with span("summary.generate"):
                    await run_summary(cid, attempt, transcript)
