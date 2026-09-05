"""Cookie-authorized SSE snapshots with access revalidation and bounded buffering."""

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import suppress

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from signal_api.auth import SessionCookie
from signal_api.database import SessionLocal
from signal_api.models import Conversation, Membership
from signal_api.session_store import get_valid_session
from signal_api.suggestion_events import events
from signal_api.suggestions import LatestSuggestionsResponse, latest_suggestions

router = APIRouter(prefix="/conversations", tags=["suggestions"])


def authorized_snapshot(token: str | None, cid: uuid.UUID) -> LatestSuggestionsResponse:
    with SessionLocal() as db:
        session = get_valid_session(db, token) if token else None
        if session is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        conversation = db.get(Conversation, cid)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        if (
            db.get(
                Membership,
                {
                    "organization_id": conversation.organization_id,
                    "user_id": session.user_id,
                },
            )
            is None
        ):
            raise HTTPException(
                status_code=403, detail="Not a member of this organization"
            )
        return latest_suggestions(db, cid)


@router.get("/{conversation_id}/suggestions/events")
async def stream_suggestions(
    conversation_id: uuid.UUID, session_token: SessionCookie = None
) -> StreamingResponse:
    queue = events.subscribe(conversation_id)
    try:
        initial = await asyncio.to_thread(
            authorized_snapshot, session_token, conversation_id
        )
    except BaseException:
        events.unsubscribe(conversation_id, queue)
        raise

    async def stream() -> AsyncIterator[str]:
        deadline = time.monotonic() + 3600
        try:
            yield "event: suggestion_state\ndata: " + initial.model_dump_json() + "\n\n"
            while time.monotonic() < deadline:
                payload = None
                with suppress(TimeoutError):
                    payload = await asyncio.wait_for(queue.get(), timeout=2)
                # No DB connection is held while waiting. Revocation stops idle
                # streams within two seconds as well as checking every event.
                try:
                    await asyncio.to_thread(
                        authorized_snapshot, session_token, conversation_id
                    )
                except HTTPException:
                    yield "event: access_revoked\ndata: {}\n\n"
                    return
                if payload is None:
                    yield ": keepalive\n\n"
                else:
                    yield (
                        "event: suggestion_state\ndata: "
                        + json.dumps(payload, ensure_ascii=False)
                        + "\n\n"
                    )
        finally:
            events.unsubscribe(conversation_id, queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"},
    )
