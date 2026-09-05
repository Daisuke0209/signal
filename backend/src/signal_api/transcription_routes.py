import asyncio
import logging
import uuid
from contextlib import suppress
from typing import Literal

from anyio import CancelScope
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from signal_api.auth import SESSION_COOKIE_NAME
from signal_api.config import get_settings
from signal_api.transcription import TranscriptionFailure, TranscriptState
from signal_api.transcription_provider import Provider, connect_provider
from signal_api.transcription_store import (
    check_access,
    close_session,
    open_session,
    persist_final,
)

router = APIRouter(tags=["transcription"])
logger = logging.getLogger("signal.transcription")


@router.websocket("/conversations/{conversation_id}/transcription/{source}")
async def transcribe(
    websocket: WebSocket,
    conversation_id: uuid.UUID,
    source: Literal["microphone", "display"],
) -> None:
    # Cookies alone do not prevent cross-site WebSocket hijacking.
    if websocket.headers.get("origin") not in get_settings().cors_origins:
        await websocket.close(code=1008)
        return
    token = websocket.cookies.get(SESSION_COOKIE_NAME, "")
    session_id: uuid.UUID | None = None
    tasks: list[asyncio.Task[None]] = []
    outcome = "failed"
    await websocket.accept()
    try:
        session_id = await run_in_threadpool(
            open_session, token, conversation_id, source
        )
        async with connect_provider() as provider:
            await websocket.send_json(
                {"type": "ready", "session_id": str(session_id), "source": source}
            )
            state = TranscriptState()

            async def receive_audio(provider: Provider) -> None:
                while True:
                    message = await websocket.receive()
                    if message["type"] == "websocket.disconnect":
                        raise WebSocketDisconnect()
                    audio = message.get("bytes")
                    if audio is not None:
                        if not audio or len(audio) > 24000 or len(audio) % 2:
                            raise TranscriptionFailure("invalid_audio")
                        await provider.send_audio(audio)
                    elif message.get("text") == '{"type":"stop"}':
                        await provider.finish()
                        if state.committed or state.completions or state.partials:
                            raise TranscriptionFailure("transcript_incomplete")
                        return
                    else:
                        raise TranscriptionFailure("invalid_message")

            async def receive_transcripts(provider: Provider) -> None:
                async for event in provider.events():
                    for update in state.apply(source, event):
                        message = None
                        if update.final:
                            message = await run_in_threadpool(
                                persist_final, token, session_id, update
                            )
                        await websocket.send_json(
                            {
                                "type": "final" if update.final else "partial",
                                "source": source,
                                "item_id": update.item_id,
                                "text": update.text,
                                "side": update.side,
                                "message": message,
                            }
                        )
                raise TranscriptionFailure("provider_disconnected")

            async def guard_access() -> None:
                # Also bounds unbounded in-memory item state and provider lifetime.
                async with asyncio.timeout(60 * 60):
                    while True:
                        await asyncio.sleep(2)
                        await run_in_threadpool(check_access, token, conversation_id)

            tasks = [
                asyncio.create_task(receive_audio(provider)),
                asyncio.create_task(receive_transcripts(provider)),
                asyncio.create_task(guard_access()),
            ]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
            outcome = "stopped"
            await websocket.send_json({"type": "stopped"})
    except WebSocketDisconnect:
        outcome = "disconnected"
    except Exception as exc:
        # Never send or log str(exc), traceback, provider messages, audio, or token.
        code = (
            str(exc)
            if isinstance(exc, TranscriptionFailure)
            else "transcription_failed"
        )
        logger.info("transcription_failed session_id=%s code=%s", session_id, code)
        with suppress(RuntimeError, WebSocketDisconnect):
            await websocket.send_json({"type": "error", "code": code})
    finally:
        with CancelScope(shield=True):
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if session_id:
                await run_in_threadpool(close_session, session_id, outcome)
            with suppress(RuntimeError, WebSocketDisconnect):
                await websocket.close(code=1000 if outcome == "stopped" else 1011)
