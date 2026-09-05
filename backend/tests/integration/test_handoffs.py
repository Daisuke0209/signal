import uuid

from fastapi.testclient import TestClient
from sqlalchemy import delete
from test_conversations import TEST_PASSWORD, create_conversation, login
from test_conversations import conversation_user as conversation_user

from signal_api.database import SessionLocal
from signal_api.main import app
from signal_api.models import ApprovalRequest, Membership, User
from signal_api.security import hash_password


def create_approved_handoff(client: TestClient, conversation_id: uuid.UUID) -> str:
    created = client.post(
        f"/conversations/{conversation_id}/approvals",
        json={
            "operation": "internal_handoff",
            "target": "営業支援",
            "input": {"summary": "技術要件を確認する"},
            "evidence": [],
        },
    )
    assert created.status_code == 201
    approval_id = created.json()["id"]
    assert (
        client.post(f"/conversations/approvals/{approval_id}/approve").status_code
        == 200
    )
    return str(approval_id)


def test_org_member_claims_and_resolves_handoff_for_original_conversation(
    conversation_user: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    organization_id, _, owner_email = conversation_user
    helper_email = f"handoff-helper-{uuid.uuid4()}@signal.local"
    approval_id: uuid.UUID | None = None
    helper_id: uuid.UUID | None = None
    try:
        with SessionLocal.begin() as db:
            helper = User(
                name="Handoff Helper",
                email=helper_email,
                password_hash=hash_password(TEST_PASSWORD),
            )
            db.add(helper)
            db.flush()
            helper_id = helper.id
            db.add(Membership(organization_id=organization_id, user_id=helper_id))
        with TestClient(app) as owner:
            login(owner, owner_email)
            conversation_id = create_conversation(owner, organization_id)
            approval_id = uuid.UUID(create_approved_handoff(owner, conversation_id))
        with TestClient(app) as helper:
            login(helper, helper_email)
            inbox = helper.get("/handoffs")
            assert inbox.status_code == 200
            assert inbox.json()[0]["approval_request_id"] == str(approval_id)
            assert (
                helper.post(f"/handoffs/{approval_id}/claim").json()["status"]
                == "claimed"
            )
            resolved = helper.post(
                f"/handoffs/{approval_id}/respond",
                json={"content": "専門担当が明日までに回答します。"},
            )
            assert resolved.status_code == 200
            assert resolved.json()["status"] == "resolved"
            assert (
                helper.post(
                    f"/handoffs/{approval_id}/respond", json={"content": "重複回答"}
                ).status_code
                == 409
            )
        with TestClient(app) as owner:
            login(owner, owner_email)
            response = owner.get(f"/conversations/{conversation_id}/handoffs")
            assert response.status_code == 200
            assert (
                response.json()[0]["response_content"]
                == "専門担当が明日までに回答します。"
            )
    finally:
        if approval_id is not None:
            with SessionLocal.begin() as db:
                db.execute(
                    delete(ApprovalRequest).where(ApprovalRequest.id == approval_id)
                )
        if helper_id is not None:
            with SessionLocal.begin() as db:
                db.execute(delete(User).where(User.id == helper_id))


def test_handoffs_require_an_authenticated_organization_member(
    conversation_user: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    organization_id, _, owner_email = conversation_user
    approval_id: uuid.UUID | None = None
    try:
        with TestClient(app) as owner:
            login(owner, owner_email)
            approval_id = uuid.UUID(
                create_approved_handoff(
                    owner, create_conversation(owner, organization_id)
                )
            )
        with TestClient(app) as anonymous:
            assert anonymous.get("/handoffs").status_code == 401
            assert anonymous.post(f"/handoffs/{approval_id}/claim").status_code == 401
    finally:
        if approval_id is not None:
            with SessionLocal.begin() as db:
                db.execute(
                    delete(ApprovalRequest).where(ApprovalRequest.id == approval_id)
                )


def test_only_one_organization_member_can_claim_a_handoff(
    conversation_user: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    organization_id, _, owner_email = conversation_user
    approval_id: uuid.UUID | None = None
    helper_ids: list[uuid.UUID] = []
    helper_emails = [
        f"handoff-claim-a-{uuid.uuid4()}@signal.local",
        f"handoff-claim-b-{uuid.uuid4()}@signal.local",
    ]
    try:
        with SessionLocal.begin() as db:
            for index, email in enumerate(helper_emails):
                helper = User(
                    name=f"Handoff Claim Helper {index}",
                    email=email,
                    password_hash=hash_password(TEST_PASSWORD),
                )
                db.add(helper)
                db.flush()
                helper_ids.append(helper.id)
                db.add(Membership(organization_id=organization_id, user_id=helper.id))
        with TestClient(app) as owner:
            login(owner, owner_email)
            approval_id = uuid.UUID(
                create_approved_handoff(
                    owner, create_conversation(owner, organization_id)
                )
            )
        with TestClient(app) as first:
            login(first, helper_emails[0])
            assert first.post(f"/handoffs/{approval_id}/claim").status_code == 200
        with TestClient(app) as second:
            login(second, helper_emails[1])
            assert second.post(f"/handoffs/{approval_id}/claim").status_code == 409
            assert (
                second.post(
                    f"/handoffs/{approval_id}/respond",
                    json={"content": "別の担当者による回答"},
                ).status_code
                == 409
            )
    finally:
        if approval_id is not None:
            with SessionLocal.begin() as db:
                db.execute(
                    delete(ApprovalRequest).where(ApprovalRequest.id == approval_id)
                )
        if helper_ids:
            with SessionLocal.begin() as db:
                db.execute(delete(User).where(User.id.in_(helper_ids)))


def test_other_organization_cannot_read_or_act_on_handoff(
    conversation_user: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    from signal_api.models import Organization

    organization_id, _, owner_email = conversation_user
    approval_id: uuid.UUID | None = None
    outsider_id: uuid.UUID | None = None
    outsider_organization_id = uuid.uuid4()
    outsider_email = f"handoff-outsider-{uuid.uuid4()}@signal.local"
    try:
        with SessionLocal.begin() as db:
            outsider_organization = Organization(
                id=outsider_organization_id,
                name="Handoff Outsider Organization",
                slug=f"handoff-outsider-{uuid.uuid4()}",
            )
            outsider = User(
                name="Handoff Outsider",
                email=outsider_email,
                password_hash=hash_password(TEST_PASSWORD),
            )
            db.add_all([outsider_organization, outsider])
            db.flush()
            outsider_id = outsider.id
            db.add(
                Membership(
                    organization_id=outsider_organization_id,
                    user_id=outsider_id,
                )
            )
        with TestClient(app) as owner:
            login(owner, owner_email)
            approval_id = uuid.UUID(
                create_approved_handoff(
                    owner, create_conversation(owner, organization_id)
                )
            )
        with TestClient(app) as outsider:
            login(outsider, outsider_email)
            assert outsider.get("/handoffs").json() == []
            assert outsider.get(f"/handoffs/{approval_id}").status_code == 403
            assert outsider.post(f"/handoffs/{approval_id}/claim").status_code == 403
            assert (
                outsider.post(
                    f"/handoffs/{approval_id}/respond",
                    json={"content": "越権回答"},
                ).status_code
                == 403
            )
    finally:
        if approval_id is not None:
            with SessionLocal.begin() as db:
                db.execute(
                    delete(ApprovalRequest).where(ApprovalRequest.id == approval_id)
                )
        if outsider_id is not None:
            with SessionLocal.begin() as db:
                db.execute(delete(User).where(User.id == outsider_id))
                db.execute(
                    delete(Organization).where(
                        Organization.id == outsider_organization_id
                    )
                )
