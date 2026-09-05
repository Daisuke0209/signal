import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from signal_api.database import SessionLocal
from signal_api.main import app
from signal_api.models import (
    Conversation,
    Membership,
    Organization,
    User,
)
from signal_api.security import hash_password

TEST_PASSWORD = "conversation-api-test-password"


@pytest.fixture
def conversation_user() -> Iterator[tuple[uuid.UUID, uuid.UUID, str]]:
    unique_id = uuid.uuid4()

    with SessionLocal() as db:
        organization = Organization(
            name="Conversation API Test Organization",
            slug=f"conversation-api-test-{unique_id}",
        )
        user = User(
            name="Conversation API Test User",
            email=f"conversation-api-test-{unique_id}@signal.local",
            password_hash=hash_password(TEST_PASSWORD),
        )
        db.add_all([organization, user])
        db.flush()
        db.add(
            Membership(
                organization_id=organization.id,
                user_id=user.id,
            )
        )
        db.commit()
        organization_id = organization.id
        user_id = user.id
        email = user.email

    try:
        yield organization_id, user_id, email
    finally:
        with SessionLocal() as db:
            db.execute(delete(User).where(User.id == user_id))
            db.execute(delete(Organization).where(Organization.id == organization_id))
            db.commit()


def login(client: TestClient, email: str) -> None:
    response = client.post(
        "/auth/login",
        json={"email": email, "password": TEST_PASSWORD},
    )
    assert response.status_code == 204


def valid_request(organization_id: uuid.UUID) -> dict[str, object]:
    return {"organization_id": str(organization_id)}


def test_create_conversation_for_authenticated_organization_member(
    conversation_user: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    organization_id, user_id, email = conversation_user

    with TestClient(app) as client:
        login(client, email)
        response = client.post(
            "/conversations",
            json=valid_request(organization_id),
        )

    assert response.status_code == 201
    body = response.json()
    assert body["organization_id"] == str(organization_id)
    assert body["created_by_user_id"] == str(user_id)
    assert body["status"] == "active"

    conversation_id = uuid.UUID(body["id"])
    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)

    assert conversation is not None
    assert conversation.organization_id == organization_id
    assert conversation.created_by_user_id == user_id


def test_create_conversation_requires_authentication() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/conversations",
            json=valid_request(uuid.uuid4()),
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_create_conversation_rejects_non_member_organization(
    conversation_user: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    organization_id, _, email = conversation_user
    other_organization_id = uuid.uuid4()

    with SessionLocal() as db:
        other_organization = Organization(
            id=other_organization_id,
            name="Other Organization",
            slug=f"other-organization-{uuid.uuid4()}",
        )
        db.add(other_organization)
        db.commit()

    try:
        with TestClient(app) as client:
            login(client, email)
            response = client.post(
                "/conversations",
                json=valid_request(other_organization_id),
            )

        assert response.status_code == 403
        assert response.json() == {"detail": "Not a member of this organization"}

        with SessionLocal() as db:
            conversation_count = db.scalar(
                select(func.count())
                .select_from(Conversation)
                .where(Conversation.organization_id == other_organization_id)
            )
        assert conversation_count == 0
    finally:
        with SessionLocal() as db:
            db.execute(
                delete(Organization).where(Organization.id == other_organization_id)
            )
            db.commit()

    assert organization_id != other_organization_id


def test_create_conversation_rejects_invalid_organization_id_without_saving(
    conversation_user: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    organization_id, _, email = conversation_user
    with TestClient(app) as client:
        login(client, email)
        response = client.post(
            "/conversations",
            json={"organization_id": "not-a-uuid"},
        )

    assert response.status_code == 422

    with SessionLocal() as db:
        conversation_count = db.scalar(
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.organization_id == organization_id)
        )
    assert conversation_count == 0
