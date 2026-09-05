import asyncio
import json
import logging
import uuid
from collections.abc import Iterator

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send

from signal_api.observability import RequestLoggingMiddleware, request_id_context


@pytest.fixture
def observed_app(caplog: pytest.LogCaptureFixture) -> Iterator[FastAPI]:
    logger = logging.getLogger("signal_tests.requests")
    caplog.set_level(logging.INFO, logger=logger.name)
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware, logger=logger)

    @app.get("/items/{item_id}")
    async def read_item(item_id: str, request: Request) -> dict[str, str | None]:
        await asyncio.sleep(0)
        return {
            "request_id": request_id_context.get(),
            "state_id": request.state.request_id,
        }

    @app.get("/failure")
    def fail() -> None:
        raise RuntimeError("sensitive-provider-message")

    yield app


def test_correlation_header_state_and_log_match_without_request_data(
    observed_app: FastAPI, caplog: pytest.LogCaptureFixture
) -> None:
    request_id = str(uuid.uuid4())
    with TestClient(observed_app) as client:
        response = client.get(
            "/items/private-item?token=secret-query",
            headers={
                "X-Request-ID": request_id,
                "Authorization": "Bearer secret-header",
                "Cookie": "session=secret-cookie",
            },
        )
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == request_id
    assert response.json() == {"request_id": request_id, "state_id": request_id}
    event = json.loads(caplog.records[-1].message)
    assert event["route"] == "/items/{item_id}"
    assert event["request_id"] == request_id
    assert event["status_code"] == 200
    assert event["duration_ms"] >= 0
    for secret in ["private-item", "secret-query", "secret-header", "secret-cookie"]:
        assert secret not in caplog.text
    assert request_id_context.get() is None


def test_invalid_id_is_replaced_and_unknown_paths_are_not_logged(
    observed_app: FastAPI, caplog: pytest.LogCaptureFixture
) -> None:
    with TestClient(observed_app) as client:
        response = client.get(
            "/sensitive-path", headers={"X-Request-ID": "secret-value"}
        )
    assert response.status_code == 404
    uuid.UUID(response.headers["X-Request-ID"])
    event = json.loads(caplog.records[-1].message)
    assert event["route"] == "unmatched"
    assert "sensitive-path" not in caplog.text
    assert "secret-value" not in caplog.text


def test_unhandled_error_has_safe_response_correlated_error_log(
    observed_app: FastAPI, caplog: pytest.LogCaptureFixture
) -> None:
    with TestClient(observed_app) as client:
        response = client.get("/failure")
    assert response.status_code == 500
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
    assert response.json()["detail"] == "Internal server error"
    event = json.loads(caplog.records[-1].message)
    assert event["status_code"] == 500
    assert event["error_type"] == "RuntimeError"
    assert event["outcome"] == "error"
    assert "sensitive-provider-message" not in caplog.text + response.text


def test_concurrent_requests_keep_separate_contexts(observed_app: FastAPI) -> None:
    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=observed_app), base_url="http://test"
        ) as client:
            ids = [str(uuid.uuid4()), str(uuid.uuid4())]
            responses = await asyncio.gather(
                *(
                    client.get("/items/demo", headers={"X-Request-ID": item})
                    for item in ids
                )
            )
            assert [response.json()["request_id"] for response in responses] == ids
            assert request_id_context.get() is None

    asyncio.run(run())


def test_http_stream_is_forwarded_before_application_finishes() -> None:
    async def run() -> None:
        delivered = asyncio.Event()
        messages: list[Message] = []

        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send(
                {"type": "http.response.body", "body": b"first", "more_body": True}
            )
            await asyncio.wait_for(delivered.wait(), timeout=1)
            await send(
                {"type": "http.response.body", "body": b"last", "more_body": False}
            )

        async def receive() -> Message:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: Message) -> None:
            messages.append(message)
            if message.get("body") == b"first":
                delivered.set()

        await RequestLoggingMiddleware(app)(
            {"type": "http", "method": "GET", "headers": [], "path": "/events"},
            receive,
            send,
        )
        assert [message.get("body") for message in messages[1:]] == [b"first", b"last"]

    asyncio.run(run())
