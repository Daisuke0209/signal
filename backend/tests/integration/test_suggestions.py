import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from signal_api.database import SessionLocal
from signal_api.main import app
from signal_api.models import (
    Conversation,
    Membership,
    Organization,
    Suggestion,
    SuggestionErrorCode,
    SuggestionKind,
    SuggestionRun,
    SuggestionRunStatus,
    User,
)
from signal_api.security import hash_password
from signal_api.suggestions import (
    SuggestionDraft,
    complete_suggestion_run,
    fail_suggestion_run,
    queue_suggestion_run,
    start_suggestion_run,
)

PASSWORD = "suggestions-test-password"


@pytest.fixture
def actor() -> Iterator[tuple[TestClient, uuid.UUID, uuid.UUID, uuid.UUID]]:
    with SessionLocal() as db:
        org = Organization(name="Suggestion org", slug=f"suggestions-{uuid.uuid4()}")
        user = User(
            name="Suggestion user",
            email=f"suggestions-{uuid.uuid4()}@signal.local",
            password_hash=hash_password(PASSWORD),
        )
        db.add_all([org, user])
        db.flush()
        db.add(Membership(organization_id=org.id, user_id=user.id))
        db.commit()
        org_id, user_id, email = org.id, user.id, user.email
    try:
        with TestClient(app) as client:
            assert (
                client.post(
                    "/auth/login", json={"email": email, "password": PASSWORD}
                ).status_code
                == 204
            )
            result = client.post(
                "/conversations", json={"organization_id": str(org_id)}
            )
            cid = uuid.UUID(result.json()["id"])
            assert (
                client.post(
                    f"/conversations/{cid}/messages",
                    json={
                        "speaker_label": "顧客",
                        "side": "customer",
                        "content": "SSOは使えますか",
                    },
                ).status_code
                == 201
            )
            yield client, cid, org_id, user_id
    finally:
        with SessionLocal() as db:
            db.execute(delete(Organization).where(Organization.id == org_id))
            db.execute(delete(User).where(User.id == user_id))
            db.commit()


def test_run_states_and_three_results_survive_new_requests(
    actor: tuple[TestClient, uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    client, cid, _, _ = actor
    url = f"/conversations/{cid}/suggestions"
    assert client.get(url).json()["latest_run"] is None
    with SessionLocal() as db:
        run = queue_suggestion_run(db, cid)
        db.commit()
        rid = run.id
    queued = client.get(url).json()["latest_run"]
    assert queued["status"] == "queued"
    assert queued["input_sequence_number"] == 1
    with SessionLocal() as db:
        start_suggestion_run(db, rid)
        db.commit()
    assert client.get(url).json()["latest_run"]["status"] == "running"
    drafts = [
        SuggestionDraft(kind=k, content=f"提案 {k.value}") for k in SuggestionKind
    ]
    with SessionLocal() as db:
        complete_suggestion_run(db, rid, drafts)
        db.commit()
    saved = client.get(url).json()["latest_run"]
    assert saved["status"] == "succeeded"
    assert saved["started_at"] and saved["completed_at"]
    assert [s["kind"] for s in saved["suggestions"]] == [
        k.value for k in SuggestionKind
    ]
    assert [s["position"] for s in saved["suggestions"]] == [0, 1, 2]
    assert client.get(url).json()["latest_run"] == saved


def test_late_completion_cannot_replace_newer_input(
    actor: tuple[TestClient, uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    client, cid, _, _ = actor
    with SessionLocal() as db:
        old = queue_suggestion_run(db, cid)
        start_suggestion_run(db, old.id)
        db.commit()
        old_id = old.id
    assert (
        client.post(
            f"/conversations/{cid}/messages",
            json={
                "speaker_label": "顧客",
                "side": "customer",
                "content": "20人で利用予定です",
            },
        ).status_code
        == 201
    )
    with SessionLocal() as db:
        new = queue_suggestion_run(db, cid)
        start_suggestion_run(db, new.id)
        complete_suggestion_run(
            db,
            new.id,
            [SuggestionDraft(kind=SuggestionKind.QUESTION, content="新しい文脈の質問")],
        )
        db.commit()
        new_id = new.id
    with SessionLocal() as db:
        complete_suggestion_run(
            db,
            old_id,
            [SuggestionDraft(kind=SuggestionKind.QUESTION, content="古い質問")],
        )
        db.commit()
    latest = client.get(f"/conversations/{cid}/suggestions").json()["latest_run"]
    assert latest["id"] == str(new_id)
    assert latest["input_sequence_number"] == 2
    assert latest["suggestions"][0]["content"] == "新しい文脈の質問"


def test_failed_run_is_safe_and_terminal(
    actor: tuple[TestClient, uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    client, cid, _, _ = actor
    with SessionLocal() as db:
        run = queue_suggestion_run(db, cid)
        fail_suggestion_run(db, run.id, SuggestionErrorCode.TIMEOUT)
        db.commit()
        rid = run.id
    body = client.get(f"/conversations/{cid}/suggestions").json()["latest_run"]
    assert body["status"] == "failed"
    assert body["error_code"] == "timeout"
    assert body["suggestions"] == []
    with SessionLocal() as db:
        with pytest.raises(ValueError, match="queued"):
            start_suggestion_run(db, rid)
        db.rollback()
        with pytest.raises(ValueError, match="running"):
            complete_suggestion_run(db, rid, [])
        db.rollback()


def test_concurrent_queues_get_unique_generations(
    actor: tuple[TestClient, uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    _, cid, _, _ = actor
    barrier = Barrier(2)

    def enqueue(_: int) -> int:
        with SessionLocal() as db:
            barrier.wait(timeout=5)
            run = queue_suggestion_run(db, cid)
            db.commit()
            return run.generation

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(enqueue, [0, 1])) == [1, 2]


def test_authorization_and_missing_conversation(
    actor: tuple[TestClient, uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    client, cid, _, user_id = actor
    with TestClient(app) as anonymous:
        assert anonymous.get(f"/conversations/{cid}/suggestions").status_code == 401
    with SessionLocal() as db:
        other = Organization(name="Other suggestions org", slug=f"other-{uuid.uuid4()}")
        db.add(other)
        db.flush()
        conversation = Conversation(
            organization_id=other.id, created_by_user_id=user_id
        )
        db.add(conversation)
        db.commit()
        other_id, other_cid = other.id, conversation.id
    try:
        assert client.get(f"/conversations/{other_cid}/suggestions").status_code == 403
        assert (
            client.get(f"/conversations/{uuid.uuid4()}/suggestions").status_code == 404
        )
    finally:
        with SessionLocal() as db:
            db.execute(delete(Organization).where(Organization.id == other_id))
            db.commit()


def test_invalid_input_snapshot_and_atomic_failure(
    actor: tuple[TestClient, uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    _, cid, _, _ = actor
    with SessionLocal() as db:
        db.add(
            SuggestionRun(
                conversation_id=cid,
                generation=1,
                input_sequence_number=999,
                status=SuggestionRunStatus.QUEUED,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        run = queue_suggestion_run(db, cid)
        start_suggestion_run(db, run.id)
        db.commit()
        rid = run.id
        # A DB constraint failure cannot publish success or a partial result set.
        bad = SuggestionDraft.model_construct(kind=SuggestionKind.QUESTION, content="")
        with pytest.raises(IntegrityError):
            complete_suggestion_run(
                db,
                rid,
                [
                    SuggestionDraft(kind=SuggestionKind.RESPONSE, content="有効な返答"),
                    bad,
                ],
            )
            db.commit()
        db.rollback()
        db.expire_all()
        persisted = db.get(SuggestionRun, rid)
        assert persisted is not None
        assert persisted.status is SuggestionRunStatus.RUNNING
        assert (
            db.scalar(
                select(func.count())
                .select_from(Suggestion)
                .where(Suggestion.run_id == rid)
            )
            == 0
        )


def test_ended_and_empty_conversations_do_not_queue(
    actor: tuple[TestClient, uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    client, cid, org_id, user_id = actor
    assert client.post(f"/conversations/{cid}/end").status_code == 200
    with SessionLocal() as db:
        with pytest.raises(ValueError, match="active"):
            queue_suggestion_run(db, cid)
        db.rollback()
        empty = Conversation(organization_id=org_id, created_by_user_id=user_id)
        db.add(empty)
        db.commit()
        with pytest.raises(ValueError, match="persisted message"):
            queue_suggestion_run(db, empty.id)
        db.rollback()


def test_response_target_is_server_validated_and_snapshotted(
    actor: tuple[TestClient, uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    client, cid, _, _ = actor
    message_id = uuid.UUID(
        client.get(f"/conversations/{cid}").json()["messages"][0]["id"]
    )
    with SessionLocal() as db:
        run = queue_suggestion_run(db, cid)
        start_suggestion_run(db, run.id)
        db.commit()
        run_id = run.id
    assert (
        client.post(
            f"/conversations/{cid}/messages",
            json={
                "speaker_label": "担当",
                "side": "sales_rep",
                "content": "確認します",
            },
        ).status_code
        == 201
    )
    later_id = uuid.UUID(
        client.get(f"/conversations/{cid}").json()["messages"][-1]["id"]
    )
    with SessionLocal() as db:
        complete_suggestion_run(
            db,
            run_id,
            [
                SuggestionDraft(
                    kind=SuggestionKind.RESPONSE,
                    content="SSO条件をご案内します",
                    customer_message_id=message_id,
                ),
                SuggestionDraft(
                    kind=SuggestionKind.RESPONSE,
                    content="不正な対象",
                    customer_message_id=later_id,
                ),
                SuggestionDraft(
                    kind=SuggestionKind.RESPONSE,
                    content="存在しない対象",
                    customer_message_id=uuid.uuid4(),
                ),
            ],
        )
        db.commit()
    suggestions = client.get(f"/conversations/{cid}/suggestions").json()["latest_run"][
        "suggestions"
    ]
    assert suggestions[0]["customer_message_id"] == str(message_id)
    assert suggestions[0]["customer_message_content"] == "SSOは使えますか"
    assert [item["customer_message_id"] for item in suggestions[1:]] == [None, None]
    assert [item["customer_message_content"] for item in suggestions[1:]] == [
        None,
        None,
    ]
