"""Authenticated, strictly bounded browser observations; never authoritative state."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from signal_api.auth import CurrentUser
from signal_api.database import get_db_session
from signal_api.domain_traces import trace, trace_context
from signal_api.models import (
    Conversation,
    Membership,
    SuggestionRun,
    TranscriptionSession,
)
from signal_api.observation_limits import limiter

router = APIRouter(prefix="/conversations", tags=["traces"])


class BrowserObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["suggestion", "transcript_partial", "transcript_final"]
    run_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    revision: int | None = Field(default=None, ge=0)
    receive_to_paint_ms: float = Field(ge=0, le=60_000, allow_inf_nan=False)

    @model_validator(mode="after")
    def matching_reference(self) -> "BrowserObservation":
        if self.kind == "suggestion":
            if (
                self.run_id is None
                or self.revision is None
                or self.session_id is not None
            ):
                raise ValueError("Suggestion run and revision required")
        elif (
            self.session_id is None
            or self.run_id is not None
            or self.revision is not None
        ):
            raise ValueError("Transcription session required")
        return self


@router.post("/{conversation_id}/observations", status_code=204)
def observe_browser(
    conversation_id: uuid.UUID,
    observation: BrowserObservation,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db_session)],
) -> Response:
    if not limiter.allow(str(current_user.id)):
        raise HTTPException(
            429, "Observation rate limit exceeded", headers={"Retry-After": "60"}
        )
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(404, "Conversation not found")
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
        raise HTTPException(403, "Not a member of this organization")
    generation = None
    run = None
    if observation.run_id is not None:
        run = db.get(SuggestionRun, observation.run_id)
        if run is None or run.conversation_id != conversation_id:
            raise HTTPException(404, "Run not found")
        if observation.revision is None or observation.revision > run.revision:
            raise HTTPException(422, "Unknown revision")
        generation = run.generation
    else:
        session = db.get(TranscriptionSession, observation.session_id)
        if session is None or session.conversation_id != conversation_id:
            raise HTTPException(404, "Transcription session not found")
    with trace_context(
        conversation_id,
        run_id=observation.run_id,
        session_id=observation.session_id,
        generation=generation,
    ):
        trace(
            f"browser.{observation.kind}.paint_opportunity",
            duration_ms=observation.receive_to_paint_ms,
            revision=observation.revision,
        )
        if run is not None:
            # Both timestamps are server-side. Includes acknowledgement transport;
            # this is an upper-bound proxy, not an exact model/render duration.
            trace(
                "suggestion.created_to_browser_ack",
                duration_ms=(datetime.now(UTC) - run.created_at).total_seconds() * 1000,
                revision=observation.revision,
            )
    return Response(status_code=204)
