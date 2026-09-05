"""Small JSON request logs without recording request content or credentials."""

import json
import logging
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

request_id_context: ContextVar[str | None] = ContextVar(
    "signal_request_id", default=None
)
request_logger = logging.getLogger("signal_api.requests")


def configure_request_logging() -> None:
    """Keep configuration idempotent across test apps and development reloads."""
    if not any(
        handler.name == "signal_request_json" for handler in request_logger.handlers
    ):
        handler = logging.StreamHandler()
        handler.set_name("signal_request_json")
        handler.setFormatter(logging.Formatter("%(message)s"))
        request_logger.addHandler(handler)
    request_logger.setLevel(logging.INFO)
    request_logger.propagate = False


def _request_id(scope: Scope) -> str:
    supplied = Headers(scope=scope).get("x-request-id", "")
    try:
        return str(uuid.UUID(supplied))
    except ValueError:
        return str(uuid.uuid4())


class RequestLoggingMiddleware:
    """Forward ASGI messages unchanged except for the correlation header.

    HTTP streaming bodies are not buffered. WebSocket/lifespan events pass through;
    their longer-lived, domain-specific traces belong to their own boundaries.
    """

    def __init__(self, app: ASGIApp, logger: logging.Logger | None = None) -> None:
        self.app = app
        self.logger = logger or request_logger

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _request_id(scope)
        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_context.set(request_id)
        started = time.perf_counter()
        status_code = 500
        response_started = False
        error_type: str | None = None

        async def send_with_id(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                status_code = message["status"]
                response_started = True
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception as error:
            error_type = type(error).__name__
            if response_started:
                # A streaming response cannot be replaced after its headers.
                raise
            response = JSONResponse(
                {"detail": "Internal server error", "request_id": request_id},
                status_code=500,
            )
            await response(scope, receive, send_with_id)
        finally:
            route = getattr(scope.get("route"), "path", None)
            event = {
                "event": "http.request",
                "timestamp": datetime.now(UTC).isoformat(),
                "request_id": request_id,
                "method": scope["method"],
                "route": route or "unmatched",
                "status_code": status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                "outcome": "error" if error_type or status_code >= 400 else "complete",
                "error_type": error_type,
            }
            try:
                self.logger.info(json.dumps(event, ensure_ascii=False))
            finally:
                request_id_context.reset(token)
