"""Content-free domain spans. Identifiers correlate work across async/thread hops."""

import json
import logging
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Literal

from signal_api.observability import request_id_context

logger = logging.getLogger("signal_api.traces")
_context: ContextVar[dict[str, str | int] | None] = ContextVar(
    "domain_trace", default=None
)
Outcome = Literal["started", "complete", "failed", "cancelled"]
SAFE_CODES = frozenset(
    {
        "interrupted",
        "timeout",
        "provider_unavailable",
        "generation_failed",
        "authentication_required",
        "conversation_unavailable",
        "conversation_ended",
        "transcription_unavailable",
        "provider_error",
        "provider_disconnected",
        "provider_backlog",
        "invalid_audio",
        "invalid_message",
        "transcript_incomplete",
        "session_unavailable",
        "speaker_conflict",
        "transcription_failed",
    }
)


def configure_domain_logging() -> None:
    if not any(handler.name == "signal_domain_json" for handler in logger.handlers):
        handler = logging.StreamHandler()
        handler.name = "signal_domain_json"
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


@contextmanager
def trace_context(
    conversation_id: uuid.UUID,
    *,
    run_id: uuid.UUID | None = None,
    generation: int | None = None,
    session_id: uuid.UUID | None = None,
) -> Iterator[None]:
    values: dict[str, str | int] = {"conversation_id": str(conversation_id)}
    for key, value in (("run_id", run_id), ("session_id", session_id)):
        if value is not None:
            values[key] = str(value)
    if generation is not None:
        values["generation"] = generation
    token = _context.set({**(_context.get() or {}), **values})
    try:
        yield
    finally:
        _context.reset(token)


def trace(
    stage: str,
    *,
    outcome: Outcome = "complete",
    duration_ms: float | None = None,
    count: int | None = None,
    revision: int | None = None,
    error_code: str | None = None,
    retryable: bool | None = None,
    source: Literal["display", "microphone"] | None = None,
) -> None:
    # Callers pass code-owned stage names. No arbitrary metadata, exception text,
    # request headers, search queries, model outputs or audio can enter this API.
    event: dict[str, object] = {
        "event": stage,
        "timestamp": datetime.now(UTC).isoformat(),
        "request_id": request_id_context.get(),
        **(_context.get() or {}),
        "outcome": outcome,
    }
    for key, value in (
        ("duration_ms", duration_ms),
        ("count", count),
        ("revision", revision),
        ("retryable", retryable),
        ("source", source),
    ):
        if value is not None:
            event[key] = round(value, 3) if isinstance(value, float) else value
    if error_code is not None:
        event["error_code"] = (
            error_code if error_code in SAFE_CODES else "operation_failed"
        )
    logger.info(json.dumps(event, ensure_ascii=False))


@contextmanager
def span(stage: str) -> Iterator[None]:
    started = time.perf_counter()
    trace(stage, outcome="started")
    try:
        yield
    except BaseException as error:
        cancelled = type(error).__name__ == "CancelledError"
        trace(
            stage,
            outcome="cancelled" if cancelled else "failed",
            duration_ms=(time.perf_counter() - started) * 1000,
            error_code="interrupted" if cancelled else "operation_failed",
        )
        raise
    else:
        trace(stage, duration_ms=(time.perf_counter() - started) * 1000)
