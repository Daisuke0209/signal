import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from starlette.websockets import WebSocketDisconnect
from test_conversations import conversation_user as conversation_user
from test_conversations import create_conversation, login

from signal_api import domain_traces
from signal_api.database import SessionLocal
from signal_api.main import app
from signal_api.models import Membership, TranscriptionSession
from signal_api.transcription import COMPLETED, DELTA, TranscriptUpdate, source_side
from signal_api.transcription_store import open_session, persist_final

ORIGIN = {"origin": "http://localhost:3000"}


class FakeProvider:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        self.closed = False
        self.count = 0

    async def send_audio(self, audio: bytes) -> None:
        self.count += 1
        if audio == b"xx":
            await self.queue.put(
                {"type": "error", "error": "private key or transcript"}
            )
            return
        kind = DELTA if self.count == 1 else COMPLETED
        if kind == COMPLETED:
            await self.queue.put(
                {"type": "input_audio_buffer.committed", "item_id": "1"}
            )
        await self.queue.put(
            {
                "type": kind,
                "item_id": "1",
                "delta": "途中の",
                "transcript": "確定した発言",
            }
        )

    async def finish(self) -> None:
        return

    async def events(self) -> AsyncIterator[dict[str, object]]:
        while True:
            yield await self.queue.get()


@pytest.fixture
def providers(monkeypatch: pytest.MonkeyPatch) -> list[FakeProvider]:
    instances: list[FakeProvider] = []

    @asynccontextmanager
    async def connect() -> AsyncIterator[FakeProvider]:
        provider = FakeProvider()
        instances.append(provider)
        try:
            yield provider
        finally:
            provider.closed = True

    monkeypatch.setattr("signal_api.transcription_routes.connect_provider", connect)
    return instances


def ws_path(conversation_id: uuid.UUID, source: str = "display") -> str:
    return f"/conversations/{conversation_id}/transcription/{source}"


def test_partial_final_persistence_dedup_and_cleanup(
    conversation_user: tuple[uuid.UUID, uuid.UUID, str],
    providers: list[FakeProvider],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    log = logging.getLogger("signal_test.transcription")
    monkeypatch.setattr(domain_traces, "logger", log)
    caplog.set_level(logging.INFO, logger=log.name)
    org, _, email = conversation_user
    with TestClient(app) as client:
        login(client, email)
        cid = create_conversation(client, org)
        with client.websocket_connect(ws_path(cid), headers=ORIGIN) as ws:
            ready = ws.receive_json()
            assert ready["type"] == "ready"
            ws.send_bytes(b"00")
            assert ws.receive_json()["text"] == "途中の"
            assert client.get(f"/conversations/{cid}").json()["messages"] == []
            ws.send_bytes(b"00")
            final = ws.receive_json()
            assert final["type"] == "final"
            assert final["message"]["side"] == "customer"
            assert final["message"]["sequence_number"] == 1
            # Database dedup also survives a fresh state machine / duplicate callback.
            duplicate = persist_final(
                client.cookies["signal_session"],
                uuid.UUID(ready["session_id"]),
                TranscriptUpdate(
                    "display", "1", source_side("display"), "確定した発言", True
                ),
            )
            assert duplicate == final["message"]
            ws.send_text('{"type":"stop"}')
            assert ws.receive_json() == {"type": "stopped"}
        assert len(client.get(f"/conversations/{cid}").json()["messages"]) == 1
    records = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == log.name
    ]
    assert {r["event"] for r in records} >= {
        "transcription.first_audio",
        "transcription.first_partial_latency",
        "transcription.persist_final",
        "transcription.ws_send",
    }
    assert all(
        r["conversation_id"] == str(cid) and r["session_id"] == ready["session_id"]
        for r in records
    )
    assert "確定した発言" not in caplog.text
    assert "途中の" not in caplog.text
    assert providers[0].closed
    with SessionLocal() as db:
        session = db.get(TranscriptionSession, uuid.UUID(ready["session_id"]))
        assert session is not None and session.status == "stopped"


@pytest.mark.parametrize(
    "case", ["anonymous", "expired", "other_org", "ended", "missing"]
)
def test_unauthorized_never_opens_provider(
    case: str,
    conversation_user: tuple[uuid.UUID, uuid.UUID, str],
    providers: list[FakeProvider],
) -> None:
    org, user, email = conversation_user
    with TestClient(app) as client:
        login(client, email)
        cid = create_conversation(client, org)
        if case == "anonymous":
            client.cookies.clear()
        elif case == "expired":
            client.post("/auth/logout")
            client.cookies.set("signal_session", "expired-session")
        elif case == "other_org":
            with SessionLocal() as db:
                db.execute(
                    delete(Membership).where(
                        Membership.organization_id == org, Membership.user_id == user
                    )
                )
                db.commit()
        elif case == "ended":
            client.post(f"/conversations/{cid}/end")
        else:
            cid = uuid.uuid4()
        with client.websocket_connect(ws_path(cid), headers=ORIGIN) as ws:
            assert ws.receive_json()["type"] == "error"
    assert providers == []


def test_origin_required(providers: list[FakeProvider]) -> None:
    with (
        TestClient(app) as client,
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(
            ws_path(uuid.uuid4()), headers={"origin": "https://evil.example"}
        ),
    ):
        pass
    assert providers == []


@pytest.mark.parametrize(
    "case", ["end", "logout", "disconnect", "provider_error", "invalid_audio"]
)
def test_active_connection_failure_cleanup(
    case: str,
    conversation_user: tuple[uuid.UUID, uuid.UUID, str],
    providers: list[FakeProvider],
    caplog: pytest.LogCaptureFixture,
) -> None:
    org, _, email = conversation_user
    with TestClient(app) as client:
        login(client, email)
        cid = create_conversation(client, org)
        with client.websocket_connect(ws_path(cid, "microphone"), headers=ORIGIN) as ws:
            ready = ws.receive_json()
            if case == "disconnect":
                ws.close()
            else:
                if case == "end":
                    client.post(f"/conversations/{cid}/end")
                elif case == "logout":
                    client.post("/auth/logout")
                else:
                    ws.send_bytes(b"xx" if case == "provider_error" else b"x")
                error = ws.receive_json()
                assert error["type"] == "error"
                assert "private" not in str(error)
    assert providers[0].closed
    assert "private key" not in caplog.text
    with SessionLocal() as db:
        session = db.get(TranscriptionSession, uuid.UUID(ready["session_id"]))
        assert session is not None and session.status != "active"


def test_both_sources_same_item_have_distinct_messages_and_empty_final_not_saved(
    conversation_user: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    org, _, email = conversation_user
    with TestClient(app) as client:
        login(client, email)
        cid = create_conversation(client, org)
        token = client.cookies["signal_session"]
        for source in ("microphone", "display"):
            sid = open_session(token, cid, source)
            update = TranscriptUpdate(source, "1", source_side(source), "発言", True)
            persist_final(token, sid, update)
            empty = TranscriptUpdate(source, "2", source_side(source), "  ", True)
            assert persist_final(token, sid, empty) is None
            assert persist_final(token, sid, empty) is None
        messages = client.get(f"/conversations/{cid}").json()["messages"]
        assert [m["side"] for m in messages] == ["sales_rep", "customer"]
        assert [m["sequence_number"] for m in messages] == [1, 2]
