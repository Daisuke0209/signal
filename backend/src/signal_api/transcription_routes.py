import asyncio
import time
import uuid
from contextlib import ExitStack, suppress
from typing import Literal

from anyio import CancelScope
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from signal_api.auth import SESSION_COOKIE_NAME
from signal_api.config import get_settings
from signal_api.domain_traces import span, trace, trace_context
from signal_api.transcription import TranscriptionFailure, TranscriptState
from signal_api.transcription_provider import Provider, connect_provider
from signal_api.transcription_store import (
    check_access,
    close_session,
    open_session,
    persist_final,
)

router = APIRouter(tags=["transcription"])


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
    first_audio: float | None = None
    first_partial = False
    with ExitStack() as trace_stack:
        trace_stack.enter_context(trace_context(conversation_id))
        await websocket.accept()
        try:
            session_id = await run_in_threadpool(
                open_session, token, conversation_id, source
            )
            trace_stack.enter_context(
                trace_context(conversation_id, session_id=session_id)
            )
            connected = time.perf_counter()
            trace("transcription.provider_connect", outcome="started", source=source)
            async with connect_provider() as provider:
                trace(
                    "transcription.provider_connect",
                    source=source,
                    duration_ms=(time.perf_counter() - connected) * 1000,
                )
                await websocket.send_json(
                    {"type": "ready", "session_id": str(session_id), "source": source}
                )
                state = TranscriptState()

                async def receive_audio(provider: Provider) -> None:
                    nonlocal first_audio
                    while True:
                        message = await websocket.receive()
                        if message["type"] == "websocket.disconnect":
                            raise WebSocketDisconnect()
                        audio = message.get("bytes")
                        if audio is not None:
                            if not audio or len(audio) > 24000 or len(audio) % 2:
                                raise TranscriptionFailure("invalid_audio")
                            if first_audio is None:
                                first_audio = time.perf_counter()
                                trace("transcription.first_audio", source=source)
                            await provider.send_audio(audio)
                        elif message.get("text") == '{"type":"stop"}':
                            await provider.finish()
                            if state.committed or state.completions or state.partials:
                                raise TranscriptionFailure("transcript_incomplete")
                            return
                        else:
                            raise TranscriptionFailure("invalid_message")

                async def receive_transcripts(provider: Provider) -> None:
                    nonlocal first_partial
                    async for event in provider.events():
                        for update in state.apply(source, event):
                            trace(
                                "transcription.final"
                                if update.final
                                else "transcription.partial",
                                source=source,
                            )
                            if (
                                not update.final
                                and not first_partial
                                and first_audio is not None
                            ):
                                first_partial = True
                                trace(
                                    "transcription.first_partial_latency",
                                    source=source,
                                    duration_ms=(time.perf_counter() - first_audio)
                                    * 1000,
                                )
                            message = None
                            if update.final:
                                with span("transcription.persist_final"):
                                    message = await run_in_threadpool(
                                        persist_final, token, session_id, update
                                    )
                            await websocket.send_json(
                                {
                                    "type": "final" if update.final else "partial",
                                    "source": source,
                                    "session_id": str(session_id),
                                    "item_id": update.item_id,
                                    "text": update.text,
                                    "side": update.side,
                                    "message": message,
                                }
                            )
                            trace("transcription.ws_send", source=source)
                    raise TranscriptionFailure("provider_disconnected")

                async def guard_access() -> None:
                    # Also bounds unbounded in-memory item state and provider lifetime.
                    async with asyncio.timeout(60 * 60):
                        while True:
                            await asyncio.sleep(2)
                            await run_in_threadpool(
                                check_access, token, conversation_id
                            )

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
            trace(
                "transcription.failure",
                outcome="failed",
                error_code=code,
                source=source,
                retryable=code
                in {"provider_error", "provider_disconnected", "transcription_failed"},
            )
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
                trace(
                    "transcription.closed",
                    source=source,
                    outcome="complete" if outcome == "stopped" else "cancelled",
                )
