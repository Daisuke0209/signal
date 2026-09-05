import asyncio
import json
import uuid
from collections.abc import Iterator

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from signal_api.config import get_settings
from signal_api.database import SessionLocal
from signal_api.main import app
from signal_api.models import (
    Conversation,
    ConversationParticipantSide,
    Membership,
    Organization,
    Suggestion,
    SuggestionRun,
    SuggestionRunStatus,
    User,
)
from signal_api.security import hash_password
from signal_api.suggestion_agent import (
    AgentOutput,
    AgentSuggestion,
    SuggestionAgent,
)
from signal_api.suggestion_events import events
from signal_api.suggestion_runtime import SuggestionRuntime, transaction
from signal_api.suggestion_stream import authorized_snapshot, stream_suggestions
from signal_api.suggestions import queue_suggestion_run, start_suggestion_run
from signal_api.transcription import TranscriptUpdate
from signal_api.transcription_store import open_session, persist_final

type Actor = tuple[TestClient, uuid.UUID, uuid.UUID, uuid.UUID, str]


@pytest.fixture
def actor() -> Iterator[tuple[TestClient, uuid.UUID, uuid.UUID, uuid.UUID, str]]:
    password = "runtime-test-only"
    with SessionLocal() as db:
        org = Organization(name="Runtime org", slug=f"runtime-{uuid.uuid4()}")
        user = User(
            name="Runtime user",
            email=f"runtime-{uuid.uuid4()}@signal.local",
            password_hash=hash_password(password),
        )
        db.add_all([org, user])
        db.flush()
        db.add(Membership(organization_id=org.id, user_id=user.id))
        cid = uuid.uuid4()
        db.add(Conversation(id=cid, organization_id=org.id, created_by_user_id=user.id))
        db.commit()
        oid, uid, email = org.id, user.id, user.email
    try:
        with TestClient(app) as client:
            assert (
                client.post(
                    "/auth/login", json={"email": email, "password": password}
                ).status_code
                == 204
            )
            token = client.cookies.get("signal_session")
            assert token
            yield client, cid, oid, uid, token
    finally:
        with SessionLocal() as db:
            db.execute(delete(Organization).where(Organization.id == oid))
            db.execute(delete(User).where(User.id == uid))
            db.commit()


def message(
    client: TestClient, cid: uuid.UUID, content: str = "SSOについて教えてください"
) -> None:
    assert (
        client.post(
            f"/conversations/{cid}/messages",
            json={"speaker_label": "顧客", "side": "customer", "content": content},
        ).status_code
        == 201
    )


def test_final_message_automatically_pushes_ordered_states_and_persists_result(
    actor: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, cid, _, _, _ = actor
    monkeypatch.setattr(get_settings(), "suggestions_enabled", True)

    async def scenario() -> None:
        def mock(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["tools"] == []  # This organization has no searchable PDFs.
            assert "no_searchable_documents" in body["input"][0]["content"]
            return httpx.Response(
                200,
                json={
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps(
                                        {
                                            "suggestions": [
                                                {
                                                    "kind": "confirmation",
                                                    "content": "確認",
                                                    "evidence_ids": [],
                                                }
                                            ]
                                        }
                                    ),
                                }
                            ],
                        }
                    ],
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as provider:
            runtime = SuggestionRuntime(SuggestionAgent(provider, "test-only"))
            await runtime.start()
            queue = events.subscribe(cid)
            try:
                await asyncio.to_thread(message, client, cid)
                states = []
                async with asyncio.timeout(5):
                    while True:
                        state = (await queue.get())["latest_run"]
                        states.append(state)
                        if state["status"] in ("succeeded", "failed"):
                            break
                assert states[0]["status"] == "queued"
                assert any(item["phase"] == "generating" for item in states)
                assert states[-1]["status"] == "succeeded"
                assert states[-1]["suggestions"][0]["kind"] == "confirmation"
                assert [item["revision"] for item in states] == sorted(
                    item["revision"] for item in states
                )
                assert (
                    client.get(f"/conversations/{cid}/suggestions").json()["latest_run"]
                    == states[-1]
                )
            finally:
                events.unsubscribe(cid, queue)
                await runtime.close()

    asyncio.run(scenario())


def test_newer_input_prevents_old_generation_result_publication(actor: Actor) -> None:
    client, cid, _, _, _ = actor
    message(client, cid)
    with SessionLocal() as db:
        old = queue_suggestion_run(db, cid)
        start_suggestion_run(db, old.id)
        db.commit()
        rid = old.id
    message(client, cid, "利用人数は20人です")
    with SessionLocal() as db:
        new = queue_suggestion_run(db, cid)
        db.commit()
        new_id = new.id
    output = AgentOutput(
        suggestions=[
            AgentSuggestion(kind="response", content="古い提案", evidence_ids=[])
        ]
    )

    async def scenario() -> None:
        async with httpx.AsyncClient() as provider:
            runtime = SuggestionRuntime(SuggestionAgent(provider, "test-only"))
            await asyncio.to_thread(
                transaction, lambda db: runtime.finish(db, cid, rid, output, {})
            )

    asyncio.run(scenario())
    with SessionLocal() as db:
        run = db.get(SuggestionRun, rid)
        assert run is not None
        assert run.status == SuggestionRunStatus.FAILED
        assert (
            db.scalar(select(func.count(Suggestion.id)).where(Suggestion.run_id == rid))
            == 0
        )
    assert client.get(f"/conversations/{cid}/suggestions").json()["latest_run"][
        "id"
    ] == str(new_id)


def test_duplicate_transcript_final_enqueues_only_once(
    actor: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, cid, _, _, token = actor
    monkeypatch.setattr(get_settings(), "suggestions_enabled", True)
    sid = open_session(token, cid, "display")
    update = TranscriptUpdate(
        source_id="display",
        item_id="test-final",
        text="こんにちは",
        final=True,
        side=ConversationParticipantSide.CUSTOMER,
    )
    first = persist_final(token, sid, update)
    assert persist_final(token, sid, update) == first
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count(SuggestionRun.id)).where(
                    SuggestionRun.conversation_id == cid
                )
            )
            == 1
        )


def test_sse_initial_snapshot_and_membership_revocation_close_stream(
    actor: Actor,
) -> None:
    _, cid, oid, uid, token = actor

    async def scenario() -> None:
        response = await stream_suggestions(cid, token)
        iterator = aiter(response.body_iterator)
        initial = await anext(iterator)
        assert isinstance(initial, str)
        assert "event: suggestion_state" in initial
        assert str(cid) in initial
        with SessionLocal() as db:
            db.execute(
                delete(Membership).where(
                    Membership.organization_id == oid, Membership.user_id == uid
                )
            )
            db.commit()
        events.publish(cid, {"conversation_id": str(cid), "latest_run": None})
        revoked = await anext(iterator)
        assert isinstance(revoked, str)
        assert "access_revoked" in revoked
        with pytest.raises(StopAsyncIteration):
            await anext(iterator)
        assert cid not in events.listeners

    asyncio.run(scenario())
    with pytest.raises(HTTPException) as caught:
        authorized_snapshot(token, cid)
    assert caught.value.status_code == 403
    with pytest.raises(HTTPException) as caught:
        authorized_snapshot(None, cid)
    assert caught.value.status_code == 401
