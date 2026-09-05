import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from test_conversations import conversation_user as conversation_user
from test_conversations import create_conversation, login, message_request

from signal_api.config import get_settings
from signal_api.database import SessionLocal
from signal_api.main import app
from signal_api.models import ConversationSummary, Membership
from signal_api.summaries import recover_summaries
from signal_api.summary_generator import MeetingSummary, SummaryFailure


def result() -> MeetingSummary:
    return MeetingSummary(
        overview="20名でSSOを利用する相談。",
        decisions=[],
        unresolved=["対応プランの確認"],
        next_actions=["担当者へ確認する"],
    )


def test_summary_persists_only_finalized_ended_conversation_and_deduplicates_start(
    conversation_user: tuple[uuid.UUID, uuid.UUID, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org, _, email = conversation_user
    generator = AsyncMock(return_value=result())
    monkeypatch.setattr("signal_api.summaries.generate_summary", generator)
    with TestClient(app) as client:
        login(client, email)
        cid = create_conversation(client, org)
        path = f"/conversations/{cid}/summary"
        assert client.get(path).json() is None
        assert client.post(path).status_code == 409
        assert (
            client.post(
                f"/conversations/{cid}/messages",
                json=message_request(content="SSOを20名で使いたい"),
            ).status_code
            == 201
        )
        client.post(f"/conversations/{cid}/end")
        monkeypatch.setattr(get_settings(), "suggestions_enabled", True)
        started = client.post(path)
        assert started.status_code == 200
        assert started.json()["status"] == "queued"
        state = client.get(path).json()
        assert state["status"] == "succeeded"
        assert state["result"] == result().model_dump()
        assert state["message_count"] == 1
        assert "SSOを20名" in generator.call_args.args[0]
        assert client.post(path).json() == state
        assert generator.call_count == 1
    with SessionLocal() as db:
        stored = db.get(ConversationSummary, cid)
        assert stored is not None and stored.result == result().model_dump()


def test_summary_failure_retry_and_restart_are_explicit(
    conversation_user: tuple[uuid.UUID, uuid.UUID, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org, _, email = conversation_user
    generator = AsyncMock(side_effect=[SummaryFailure("timeout"), result()])
    monkeypatch.setattr("signal_api.summaries.generate_summary", generator)
    with TestClient(app) as client:
        login(client, email)
        cid = create_conversation(client, org)
        client.post(f"/conversations/{cid}/messages", json=message_request())
        client.post(f"/conversations/{cid}/end")
        monkeypatch.setattr(get_settings(), "suggestions_enabled", True)
        path = f"/conversations/{cid}/summary"
        assert client.post(path).status_code == 200
        state = client.get(path).json()
        assert state["status"] == "failed" and state["error_code"] == "timeout"
        assert state["result"] is None
        assert client.post(path).json()["attempt"] == 2
        assert client.get(path).json()["status"] == "succeeded"
        with SessionLocal() as db:
            stored = db.get(ConversationSummary, cid)
            assert stored
            stored.status, stored.result = "generating", None
            db.commit()
        recover_summaries()
        state = client.get(path).json()
        assert state["status"] == "failed" and state["error_code"] == "interrupted"


def test_summary_auth_empty_and_disabled_model(
    conversation_user: tuple[uuid.UUID, uuid.UUID, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org, uid, email = conversation_user
    with TestClient(app) as client:
        login(client, email)
        cid = create_conversation(client, org)
        client.post(f"/conversations/{cid}/end")
        path = f"/conversations/{cid}/summary"
        assert client.post(path).status_code == 503
        monkeypatch.setattr(get_settings(), "suggestions_enabled", True)
        assert client.post(path).status_code == 422
        with SessionLocal() as db:
            membership = db.get(Membership, {"organization_id": org, "user_id": uid})
            assert membership
            db.delete(membership)
            db.commit()
        assert client.get(path).status_code == 403
        assert client.post(path).status_code == 403
        client.cookies.clear()
        assert client.get(path).status_code == 401
        assert client.post(path).status_code == 401


def test_queued_summary_start_does_not_schedule_duplicate_jobs(
    conversation_user: tuple[uuid.UUID, uuid.UUID, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org, _, email = conversation_user
    with TestClient(app) as client:
        login(client, email)
        cid = create_conversation(client, org)
        client.post(f"/conversations/{cid}/messages", json=message_request())
        client.post(f"/conversations/{cid}/end")
        monkeypatch.setattr(get_settings(), "suggestions_enabled", True)
        worker = AsyncMock()
        monkeypatch.setattr(app.state.summary_worker, "run", worker)
        first = client.post(f"/conversations/{cid}/summary").json()
        second = client.post(f"/conversations/{cid}/summary").json()
        assert first == second
        assert first["status"] == "queued"
        assert worker.call_count == 1
