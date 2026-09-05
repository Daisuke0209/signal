import json
import logging
import uuid

import pytest
from fastapi.testclient import TestClient
from test_conversations import conversation_user as conversation_user
from test_conversations import create_conversation, login

from signal_api import domain_traces
from signal_api.database import SessionLocal
from signal_api.main import app
from signal_api.models import Membership
from signal_api.transcription_store import open_session


def test_browser_observations_authorize_and_reject_arbitrary_content(
    conversation_user: tuple[uuid.UUID, uuid.UUID, str],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = logging.getLogger("signal_test.observations")
    monkeypatch.setattr(domain_traces, "logger", logger)
    caplog.set_level(logging.INFO, logger=logger.name)
    org, uid, email = conversation_user
    with TestClient(app) as client:
        login(client, email)
        cid = create_conversation(client, org)
        other = create_conversation(client, org)
        sid = open_session(client.cookies["signal_session"], cid, "display")
        payload = {
            "kind": "transcript_partial",
            "session_id": str(sid),
            "receive_to_paint_ms": 32.5,
        }
        path = f"/conversations/{cid}/observations"
        assert client.post(path, json=payload).status_code == 204
        event = json.loads(
            [r for r in caplog.records if r.name == logger.name][-1].message
        )
        assert event["event"] == "browser.transcript_partial.paint_opportunity"
        assert event["conversation_id"] == str(cid)
        assert event["session_id"] == str(sid)
        assert event["duration_ms"] == 32.5
        assert (
            client.post(
                f"/conversations/{other}/observations", json=payload
            ).status_code
            == 404
        )
        assert (
            client.post(path, json={**payload, "content": "secret"}).status_code == 422
        )
        assert (
            client.post(path, json={**payload, "receive_to_paint_ms": -1}).status_code
            == 422
        )
        assert (
            client.post(
                path, json={**payload, "receive_to_paint_ms": 60001}
            ).status_code
            == 422
        )
        assert (
            client.post(path, json={**payload, "kind": "suggestion"}).status_code == 422
        )
        with SessionLocal() as db:
            membership = db.get(Membership, {"organization_id": org, "user_id": uid})
            assert membership
            db.delete(membership)
            db.commit()
        assert client.post(path, json=payload).status_code == 403
        client.cookies.clear()
        assert client.post(path, json=payload).status_code == 401
    assert "secret" not in caplog.text


def test_observation_burst_is_rejected_before_domain_queries(
    conversation_user: tuple[uuid.UUID, uuid.UUID, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from signal_api import trace_routes
    from signal_api.observation_limits import ObservationLimiter

    org, _, email = conversation_user
    monkeypatch.setattr(trace_routes, "limiter", ObservationLimiter(limit=1))
    with TestClient(app) as client:
        login(client, email)
        cid = create_conversation(client, org)
        sid = open_session(client.cookies["signal_session"], cid, "display")
        payload = {
            "kind": "transcript_partial",
            "session_id": str(sid),
            "receive_to_paint_ms": 10,
        }
        assert (
            client.post(f"/conversations/{cid}/observations", json=payload).status_code
            == 204
        )
        # Even a nonexistent conversation reaches the limiter before domain lookups.
        response = client.post(
            f"/conversations/{uuid.uuid4()}/observations", json=payload
        )
        assert response.status_code == 429
        assert response.headers["retry-after"] == "60"
