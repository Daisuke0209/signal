"""Durable suggestion state; generation is an internal service responsibility."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signal_api.auth import CurrentUser
from signal_api.database import get_db_session
from signal_api.models import (
    Conversation,
    ConversationMessage,
    ConversationStatus,
    Membership,
    Suggestion,
    SuggestionErrorCode,
    SuggestionKind,
    SuggestionRun,
    SuggestionRunStatus,
)
from signal_api.suggestion_agent import Evidence

router = APIRouter(prefix="/conversations", tags=["suggestions"])
DatabaseSession = Annotated[Session, Depends(get_db_session)]


class SuggestionDraft(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    kind: SuggestionKind
    content: str = Field(min_length=1, max_length=4000)
    sources: list[Evidence] = Field(default_factory=list, max_length=5)


class SuggestionResponse(SuggestionDraft):
    id: uuid.UUID
    position: int


class SuggestionRunResponse(BaseModel):
    id: uuid.UUID
    generation: int
    revision: int
    phase: str | None
    input_sequence_number: int
    status: SuggestionRunStatus
    error_code: SuggestionErrorCode | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    suggestions: list[SuggestionResponse]


class LatestSuggestionsResponse(BaseModel):
    conversation_id: uuid.UUID
    latest_run: SuggestionRunResponse | None


def queue_suggestion_run(db: Session, conversation_id: uuid.UUID) -> SuggestionRun:
    """Snapshot the latest persisted message; caller commits before any LLM I/O.

    Trusted internal service only. The HTTP/event boundary must authorize its user.
    The conversation lock also serializes message append and conversation ending.
    """
    conversation = db.scalar(
        select(Conversation).where(Conversation.id == conversation_id).with_for_update()
    )
    if conversation is None or conversation.status is not ConversationStatus.ACTIVE:
        raise ValueError("An active conversation is required")
    input_sequence = db.scalar(
        select(func.max(ConversationMessage.sequence_number)).where(
            ConversationMessage.conversation_id == conversation_id
        )
    )
    if input_sequence is None:
        raise ValueError("At least one persisted message is required")
    previous_generation = db.scalar(
        select(func.max(SuggestionRun.generation)).where(
            SuggestionRun.conversation_id == conversation_id
        )
    )
    run = SuggestionRun(
        conversation_id=conversation_id,
        generation=(previous_generation or 0) + 1,
        input_sequence_number=input_sequence,
        status=SuggestionRunStatus.QUEUED,
    )
    db.add(run)
    db.flush()
    return run


def _locked_run(db: Session, run_id: uuid.UUID) -> SuggestionRun:
    run = db.scalar(
        select(SuggestionRun)
        .where(SuggestionRun.id == run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if run is None:
        raise ValueError("Suggestion run not found")
    return run


def start_suggestion_run(db: Session, run_id: uuid.UUID) -> SuggestionRun:
    run = _locked_run(db, run_id)
    if run.status is not SuggestionRunStatus.QUEUED:
        raise ValueError("Only a queued run can start")
    run.status = SuggestionRunStatus.RUNNING
    run.phase = "generating"
    run.revision += 1
    run.started_at = datetime.now(UTC)
    db.flush()
    return run


def complete_suggestion_run(
    db: Session, run_id: uuid.UUID, drafts: list[SuggestionDraft]
) -> SuggestionRun:
    if len(drafts) > 12:
        raise ValueError("At most 12 suggestions are allowed")
    run = _locked_run(db, run_id)
    if run.status is not SuggestionRunStatus.RUNNING:
        raise ValueError("Only a running run can complete")
    for position, draft in enumerate(drafts):
        db.add(
            Suggestion(
                run_id=run.id,
                kind=draft.kind,
                position=position,
                content=draft.content,
                sources=[source.model_dump(mode="json") for source in draft.sources],
            )
        )
    run.status = SuggestionRunStatus.SUCCEEDED
    run.phase = None
    run.revision += 1
    run.completed_at = datetime.now(UTC)
    db.flush()
    return run


def fail_suggestion_run(
    db: Session, run_id: uuid.UUID, code: SuggestionErrorCode
) -> SuggestionRun:
    run = _locked_run(db, run_id)
    if run.status not in (SuggestionRunStatus.QUEUED, SuggestionRunStatus.RUNNING):
        raise ValueError("A terminal run cannot change")
    run.status = SuggestionRunStatus.FAILED
    run.phase = None
    run.revision += 1
    run.error_code = code
    run.completed_at = datetime.now(UTC)
    db.flush()
    return run


@router.get("/{conversation_id}/suggestions", response_model=LatestSuggestionsResponse)
def get_latest_suggestions(
    conversation_id: uuid.UUID, db: DatabaseSession, current_user: CurrentUser
) -> LatestSuggestionsResponse:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if (
        db.get(
            Membership,
            {
                "organization_id": conversation.organization_id,
                "user_id": current_user.id,
            },
        )
        is None
    ):
        raise HTTPException(status_code=403, detail="Not a member of this organization")
    return latest_suggestions(db, conversation_id)


def latest_suggestions(
    db: Session, conversation_id: uuid.UUID
) -> LatestSuggestionsResponse:
    """Internal snapshot read. The HTTP/event boundary authorizes before calling."""
    # Generation order, never completion order: old completions cannot replace new runs.
    run = db.scalar(
        select(SuggestionRun)
        .where(SuggestionRun.conversation_id == conversation_id)
        .order_by(SuggestionRun.generation.desc())
        .limit(1)
    )
    if run is None:
        return LatestSuggestionsResponse(
            conversation_id=conversation_id, latest_run=None
        )
    suggestions = []
    if run.status is SuggestionRunStatus.SUCCEEDED:
        # Terminal runs are immutable. Avoid exposing results committed after an
        # earlier read observed this run as still running (READ COMMITTED).
        suggestions = list(
            db.scalars(
                select(Suggestion)
                .where(Suggestion.run_id == run.id)
                .order_by(Suggestion.position)
            )
        )
    return LatestSuggestionsResponse(
        conversation_id=conversation_id,
        latest_run=SuggestionRunResponse(
            id=run.id,
            generation=run.generation,
            revision=run.revision,
            phase=run.phase,
            input_sequence_number=run.input_sequence_number,
            status=run.status,
            error_code=run.error_code,
            created_at=run.created_at,
            started_at=run.started_at,
            completed_at=run.completed_at,
            suggestions=[
                SuggestionResponse(
                    id=s.id,
                    kind=s.kind,
                    position=s.position,
                    content=s.content,
                    sources=[Evidence.model_validate(source) for source in s.sources],
                )
                for s in suggestions
            ],
        ),
    )
