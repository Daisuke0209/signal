import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from test_conversations import TEST_PASSWORD, create_conversation, login
from test_conversations import conversation_user as conversation_user

from signal_api.database import SessionLocal
from signal_api.main import app
from signal_api.models import (
    ApprovalRequest,
    InternalHandoff,
    Membership,
    Organization,
    User,
)
from signal_api.security import hash_password


def approval_payload() -> dict[str, object]:
    return {
        "operation": "internal_handoff",
        "target": "営業支援",
        "input": {"summary": "確認依頼"},
        "evidence": [],
    }


def delete_approval(approval_id: uuid.UUID | None) -> None:
    if approval_id is None:
        return
    with SessionLocal.begin() as db:
        db.execute(delete(ApprovalRequest).where(ApprovalRequest.id == approval_id))


def handoff_count(approval_id: uuid.UUID) -> int:
    with SessionLocal() as db:
        return int(
            db.scalar(
                select(func.count())
                .select_from(InternalHandoff)
                .where(InternalHandoff.approval_request_id == approval_id)
            )
            or 0
        )


def test_approve_is_idempotent_and_creates_one_internal_handoff(
    conversation_user: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    organization_id, _, email = conversation_user
    approval_id: uuid.UUID | None = None
    try:
        with TestClient(app) as client:
            login(client, email)
            conversation_id = create_conversation(client, organization_id)
            created = client.post(
                f"/conversations/{conversation_id}/approvals",
                json=approval_payload(),
            )
            assert created.status_code == 201
            assert (
                client.get(f"/conversations/{conversation_id}/approvals").json()[0][
                    "id"
                ]
                == created.json()["id"]
            )
            approval_id = uuid.UUID(created.json()["id"])

            first = client.post(f"/conversations/approvals/{approval_id}/approve")
            second = client.post(f"/conversations/approvals/{approval_id}/approve")

        assert first.status_code == second.status_code == 200
        assert first.json()["status"] == second.json()["status"] == "approved"
        assert handoff_count(approval_id) == 1
    finally:
        delete_approval(approval_id)


def test_rejected_approval_cannot_be_approved_or_create_handoff(
    conversation_user: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    organization_id, _, email = conversation_user
    approval_id: uuid.UUID | None = None
    try:
        with TestClient(app) as client:
            login(client, email)
            conversation_id = create_conversation(client, organization_id)
            created = client.post(
                f"/conversations/{conversation_id}/approvals",
                json=approval_payload(),
            )
            assert created.status_code == 201
            approval_id = uuid.UUID(created.json()["id"])

            assert (
                client.post(
                    f"/conversations/approvals/{approval_id}/reject"
                ).status_code
                == 200
            )
            assert (
                client.post(
                    f"/conversations/approvals/{approval_id}/approve"
                ).status_code
                == 409
            )

        assert handoff_count(approval_id) == 0
    finally:
        delete_approval(approval_id)


def test_approval_routes_require_authentication(
    conversation_user: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    organization_id, _, email = conversation_user
    approval_id: uuid.UUID | None = None
    try:
        with TestClient(app) as authenticated:
            login(authenticated, email)
            conversation_id = create_conversation(authenticated, organization_id)
            created = authenticated.post(
                f"/conversations/{conversation_id}/approvals",
                json=approval_payload(),
            )
            assert created.status_code == 201
            approval_id = uuid.UUID(created.json()["id"])

        with TestClient(app) as anonymous:
            assert (
                anonymous.get(f"/conversations/{conversation_id}/approvals").status_code
                == 401
            )
            assert (
                anonymous.post(
                    f"/conversations/approvals/{approval_id}/approve"
                ).status_code
                == 401
            )
    finally:
        delete_approval(approval_id)


def test_other_organization_member_cannot_decide_approval(
    conversation_user: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    organization_id, _, email = conversation_user
    foreign_organization_id = uuid.uuid4()
    foreign_user_id: uuid.UUID | None = None
    foreign_email = f"approval-foreign-{uuid.uuid4()}@signal.local"
    approval_id: uuid.UUID | None = None
    try:
        with SessionLocal.begin() as db:
            organization = Organization(
                id=foreign_organization_id,
                name="Approval Foreign Organization",
                slug=f"approval-foreign-{uuid.uuid4()}",
            )
            user = User(
                name="Approval Foreign User",
                email=foreign_email,
                password_hash=hash_password(TEST_PASSWORD),
            )
            db.add_all([organization, user])
            db.flush()
            foreign_user_id = user.id
            db.add(
                Membership(
                    organization_id=foreign_organization_id,
                    user_id=foreign_user_id,
                )
            )

        with TestClient(app) as owner:
            login(owner, email)
            conversation_id = create_conversation(owner, organization_id)
            created = owner.post(
                f"/conversations/{conversation_id}/approvals",
                json=approval_payload(),
            )
            assert created.status_code == 201
            approval_id = uuid.UUID(created.json()["id"])

        with TestClient(app) as foreign:
            login(foreign, foreign_email)
            assert (
                foreign.get(f"/conversations/{conversation_id}/approvals").status_code
                == 403
            )
            assert (
                foreign.post(
                    f"/conversations/approvals/{approval_id}/approve"
                ).status_code
                == 403
            )
    finally:
        delete_approval(approval_id)
        if foreign_user_id is not None:
            with SessionLocal.begin() as db:
                db.execute(delete(User).where(User.id == foreign_user_id))
                db.execute(
                    delete(Organization).where(
                        Organization.id == foreign_organization_id
                    )
                )


def test_concurrent_approvals_create_one_internal_handoff(
    conversation_user: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    organization_id, _, email = conversation_user
    approval_id: uuid.UUID | None = None
    try:
        with TestClient(app) as client:
            login(client, email)
            conversation_id = create_conversation(client, organization_id)
            created = client.post(
                f"/conversations/{conversation_id}/approvals",
                json=approval_payload(),
            )
            assert created.status_code == 201
            approval_id = uuid.UUID(created.json()["id"])

        def approve() -> int:
            with TestClient(app) as client:
                login(client, email)
                return int(
                    client.post(
                        f"/conversations/approvals/{approval_id}/approve"
                    ).status_code
                )

        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(lambda _: approve(), range(2)))

        assert statuses == [200, 200]
        assert handoff_count(approval_id) == 1
    finally:
        delete_approval(approval_id)
