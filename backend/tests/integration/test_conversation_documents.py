import asyncio
import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from signal_api.config import get_settings
from signal_api.database import SessionLocal
from signal_api.main import app
from signal_api.models import (
    Conversation,
    Document,
    DocumentPage,
    DocumentProcessingStatus,
    Membership,
    Organization,
    Suggestion,
    SuggestionRun,
    SuggestionRunStatus,
    User,
)
from signal_api.security import hash_password
from signal_api.suggestion_agent import AgentOutput, AgentSuggestion, SuggestionAgent
from signal_api.suggestion_runtime import SuggestionRuntime, transaction
from signal_api.suggestions import start_suggestion_run


@dataclass
class Case:
    client: TestClient
    cid: uuid.UUID
    foreign_cid: uuid.UUID
    ready: list[uuid.UUID]
    pending: uuid.UUID
    foreign_document: uuid.UUID

    @property
    def url(self) -> str:
        return f"/conversations/{self.cid}/documents"

    def put(self, ids: list[uuid.UUID]) -> httpx.Response:
        return cast(
            httpx.Response,
            self.client.put(self.url, json={"document_ids": list(map(str, ids))}),
        )


@pytest.fixture
def case() -> Iterator[Case]:
    with SessionLocal() as db:
        orgs = [
            Organization(name="Selection test", slug=f"selection-{uuid.uuid4()}")
            for _ in range(2)
        ]
        user = User(
            name="Selection user",
            email=f"selection-{uuid.uuid4()}@signal.local",
            password_hash=hash_password("selection-test"),
        )
        db.add_all([*orgs, user])
        db.flush()
        db.add(Membership(organization_id=orgs[0].id, user_id=user.id))
        conversations = [
            Conversation(organization_id=org.id, created_by_user_id=user.id)
            for org in orgs
        ]
        docs = [
            Document(
                organization_id=orgs[1 if i == 3 else 0].id,
                uploaded_by_user_id=user.id,
                filename=f"{4 - i}-仕様.pdf",
                content_type="application/pdf",
                byte_size=100,
                storage_key=str(uuid.uuid4()),
                processing_status=DocumentProcessingStatus.PENDING
                if i == 2
                else DocumentProcessingStatus.READY,
            )
            for i in range(4)
        ]
        db.add_all([*conversations, *docs])
        db.flush()
        db.add_all(
            [
                DocumentPage(
                    document_id=doc.id, page_number=1, content=f"SSO {doc.filename}"
                )
                for doc in docs
                if doc.processing_status is DocumentProcessingStatus.READY
            ]
        )
        db.commit()
        org_ids, uid, email = [org.id for org in orgs], user.id, user.email
        cid, foreign_cid = [c.id for c in conversations]
        doc_ids = [doc.id for doc in docs]
    try:
        with TestClient(app) as client:
            assert (
                client.post(
                    "/auth/login", json={"email": email, "password": "selection-test"}
                ).status_code
                == 204
            )
            yield Case(client, cid, foreign_cid, doc_ids[:2], doc_ids[2], doc_ids[3])
    finally:
        with SessionLocal() as db:
            db.execute(delete(Organization).where(Organization.id.in_(org_ids)))
            db.execute(delete(User).where(User.id == uid))
            db.commit()


def test_selection_authorization_and_ready_boundary(case: Case) -> None:
    with TestClient(app) as anonymous:
        assert anonymous.get(case.url).status_code == 401
        assert anonymous.put(case.url, json={"document_ids": []}).status_code == 401
    foreign_url = f"/conversations/{case.foreign_cid}/documents"
    assert case.client.get(foreign_url).status_code == 403
    assert case.client.put(foreign_url, json={"document_ids": []}).status_code == 403
    for invalid in [case.pending, case.foreign_document, uuid.uuid4()]:
        assert case.put([*case.ready, invalid]).status_code == 422
        assert case.client.get(case.url).json() == []
    assert case.put([case.ready[0]] * 101).status_code == 422


def test_selection_replace_clear_order_and_ended_write(case: Case) -> None:
    response = case.put([*case.ready, case.ready[0]])
    assert response.status_code == 200
    assert len(response.json()) == 2
    names = [item["filename"] for item in response.json()]
    assert names == sorted(names)
    assert case.client.get(case.url).json() == response.json()
    assert case.put([case.ready[0]]).status_code == 200
    assert len(case.client.get(case.url).json()) == 1
    assert case.put([]).json() == []
    assert case.client.get(case.url).json() == []
    assert case.client.post(f"/conversations/{case.cid}/end").status_code == 200
    assert case.put(case.ready).status_code == 409


def test_selection_change_invalidates_old_generation_and_noop_preserves_generation(
    case: Case, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert (
        case.client.post(
            f"/conversations/{case.cid}/messages",
            json={
                "speaker_label": "顧客",
                "side": "customer",
                "content": "SSOの条件は？",
            },
        ).status_code
        == 201
    )
    monkeypatch.setattr(get_settings(), "suggestions_enabled", True)
    assert case.put(case.ready).status_code == 200
    with SessionLocal() as db:
        run = db.scalar(
            select(SuggestionRun).where(SuggestionRun.conversation_id == case.cid)
        )
        assert run is not None
        rid = run.id
        start_suggestion_run(db, rid)
        db.commit()
    assert case.put(list(reversed(case.ready))).status_code == 200
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count(SuggestionRun.id)).where(
                    SuggestionRun.conversation_id == case.cid
                )
            )
            == 1
        )
    assert case.put([]).status_code == 200
    output = AgentOutput(
        suggestions=[
            AgentSuggestion(
                kind="response",
                content="古い資料の提案",
                evidence_ids=[],
                customer_message_id=None,
            )
        ]
    )

    async def finish_old() -> None:
        async with httpx.AsyncClient() as client:
            runtime = SuggestionRuntime(SuggestionAgent(client, "unused"))
            transaction(lambda db: runtime.finish(db, case.cid, rid, output, {}))

    asyncio.run(finish_old())
    with SessionLocal() as db:
        run = db.get(SuggestionRun, rid)
        assert run and run.status is SuggestionRunStatus.FAILED
        assert (
            db.scalar(select(func.count(Suggestion.id)).where(Suggestion.run_id == rid))
            == 0
        )
        assert (
            db.scalar(
                select(func.count(SuggestionRun.id)).where(
                    SuggestionRun.conversation_id == case.cid
                )
            )
            == 2
        )


def test_runtime_passes_only_selected_documents_to_search(
    case: Case, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert (
        case.client.post(
            f"/conversations/{case.cid}/messages",
            json={"speaker_label": "顧客", "side": "customer", "content": "SSO"},
        ).status_code
        == 201
    )
    monkeypatch.setattr(get_settings(), "suggestions_enabled", True)
    assert case.put([case.ready[0]]).status_code == 200
    with SessionLocal() as db:
        run = db.scalar(
            select(SuggestionRun).where(SuggestionRun.conversation_id == case.cid)
        )
        assert run
        rid = run.id
    calls = 0

    def provider(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        output: list[dict[str, object]]
        if calls == 1:
            output = [
                {
                    "type": "function_call",
                    "name": "search_documents",
                    "call_id": "search",
                    "arguments": '{"query":"SSO"}',
                }
            ]
        else:
            body = json.loads(request.content)
            evidence = json.loads(body["input"][-1]["output"])
            assert [item["document_id"] for item in evidence] == [str(case.ready[0])]
            output = [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": (
                                '{"suggestions":[{"kind":"response",'
                                '"content":"確認","evidence_ids":["s1p1"],"customer_message_id":null}]}'
                            ),
                        }
                    ],
                }
            ]
        return httpx.Response(200, json={"status": "completed", "output": output})

    async def generate() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            runtime = SuggestionRuntime(SuggestionAgent(client, "test-only"))
            await runtime.work(case.cid, rid)

    asyncio.run(generate())
    assert calls == 2
    result = case.client.get(f"/conversations/{case.cid}/suggestions").json()[
        "latest_run"
    ]
    assert result["status"] == "succeeded"
    assert result["suggestions"][0]["sources"][0]["document_id"] == str(case.ready[0])
