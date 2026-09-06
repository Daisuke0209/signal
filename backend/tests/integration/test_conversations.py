import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from signal_api.database import SessionLocal
from signal_api.main import app
from signal_api.models import (
    Conversation,
    ConversationMessage,
    ConversationParticipant,
    ConversationStatus,
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


def create_conversation(client: TestClient, organization_id: uuid.UUID) -> uuid.UUID:
    response = client.post(
        "/conversations",
        json=valid_request(organization_id),
    )
    assert response.status_code == 201
    return uuid.UUID(response.json()["id"])


def message_request(
    speaker_label: str = "speaker_1",
    side: str = "customer",
    content: str = "案件管理に時間がかかっています。",
) -> dict[str, str]:
    return {
        "speaker_label": speaker_label,
        "side": side,
        "content": content,
    }


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
        listed = client.get("/conversations").json()
        detail = client.get(f"/conversations/{response.json()['id']}").json()

    assert response.status_code == 201
    body = response.json()
    assert body["organization_id"] == str(organization_id)
    assert body["created_by_user_id"] == str(user_id)
    assert body["status"] == "active"
    assert body["created_at"] == listed[0]["created_at"] == detail["created_at"]

    conversation_id = uuid.UUID(body["id"])
    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)

    assert conversation is not None
    assert conversation.organization_id == organization_id
    assert conversation.created_by_user_id == user_id
    assert datetime.fromisoformat(body["created_at"]) == conversation.created_at


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


def test_list_conversations_returns_only_member_organizations(
    conversation_user: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    organization_id, user_id, email = conversation_user
    other_organization_id = uuid.uuid4()
    created_at = datetime.now(UTC)

    with SessionLocal() as db:
        other_organization = Organization(
            id=other_organization_id,
            name="Conversation List Other Organization",
            slug=f"conversation-list-other-{uuid.uuid4()}",
        )
        db.add(other_organization)
        db.flush()
        db.add(
            Conversation(
                organization_id=other_organization_id,
                created_by_user_id=user_id,
            )
        )
        oldest_conversation = Conversation(
            organization_id=organization_id,
            created_by_user_id=user_id,
            created_at=created_at - timedelta(minutes=1),
        )
        newest_conversation = Conversation(
            organization_id=organization_id,
            created_by_user_id=user_id,
            created_at=created_at,
        )
        db.add_all([oldest_conversation, newest_conversation])
        db.commit()
        oldest_conversation_id = oldest_conversation.id
        newest_conversation_id = newest_conversation.id

    try:
        with TestClient(app) as client:
            login(client, email)
            response = client.get("/conversations")

        assert response.status_code == 200
        body = response.json()
        assert [conversation["id"] for conversation in body] == [
            str(newest_conversation_id),
            str(oldest_conversation_id),
        ]
        assert all(
            conversation["organization_id"] == str(organization_id)
            for conversation in body
        )
        assert all(conversation["status"] == "active" for conversation in body)
        assert all(conversation["created_at"] for conversation in body)
    finally:
        with SessionLocal() as db:
            db.execute(
                delete(Organization).where(Organization.id == other_organization_id)
            )
            db.commit()


def test_get_conversation_returns_participants_and_messages_in_sequence_order(
    conversation_user: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    organization_id, user_id, email = conversation_user

    with TestClient(app) as client:
        login(client, email)
        conversation_id = create_conversation(client, organization_id)
        customer_response = client.post(
            f"/conversations/{conversation_id}/messages",
            json=message_request(
                speaker_label="customer_1",
                content="手作業が多く、対応が遅れています。",
            ),
        )
        sales_rep_response = client.post(
            f"/conversations/{conversation_id}/messages",
            json=message_request(
                speaker_label="sales_rep_1",
                side="sales_rep",
                content="特に時間がかかる業務を教えてください。",
            ),
        )
        detail_response = client.get(f"/conversations/{conversation_id}")

    assert customer_response.status_code == 201
    assert sales_rep_response.status_code == 201
    assert detail_response.status_code == 200
    body = detail_response.json()
    assert body["id"] == str(conversation_id)
    assert body["organization_id"] == str(organization_id)
    assert body["created_by_user_id"] == str(user_id)
    assert body["created_at"]
    participants = {
        (participant["speaker_label"], participant["side"])
        for participant in body["participants"]
    }
    assert participants == {
        ("customer_1", "customer"),
        ("sales_rep_1", "sales_rep"),
    }
    assert [message["sequence_number"] for message in body["messages"]] == [1, 2]
    assert [message["speaker_label"] for message in body["messages"]] == [
        "customer_1",
        "sales_rep_1",
    ]
    assert [message["content"] for message in body["messages"]] == [
        "手作業が多く、対応が遅れています。",
        "特に時間がかかる業務を教えてください。",
    ]


def test_get_conversation_requires_authentication() -> None:
    with TestClient(app) as client:
        list_response = client.get("/conversations")
        detail_response = client.get(f"/conversations/{uuid.uuid4()}")

    assert list_response.status_code == 401
    assert detail_response.status_code == 401
    assert list_response.json() == {"detail": "Authentication required"}
    assert detail_response.json() == {"detail": "Authentication required"}


def test_get_conversation_rejects_non_member(
    conversation_user: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    _, user_id, email = conversation_user
    other_organization_id = uuid.uuid4()

    with SessionLocal() as db:
        db.add(
            Organization(
                id=other_organization_id,
                name="Conversation Detail Other Organization",
                slug=f"conversation-detail-other-{uuid.uuid4()}",
            )
        )
        db.flush()
        conversation = Conversation(
            organization_id=other_organization_id,
            created_by_user_id=user_id,
        )
        db.add(conversation)
        db.commit()
        conversation_id = conversation.id

    try:
        with TestClient(app) as client:
            login(client, email)
            response = client.get(f"/conversations/{conversation_id}")

        assert response.status_code == 403
        assert response.json() == {"detail": "Not a member of this organization"}
    finally:
        with SessionLocal() as db:
            db.execute(
                delete(Organization).where(Organization.id == other_organization_id)
            )
            db.commit()


def test_get_conversation_returns_not_found_for_unknown_conversation(
    conversation_user: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    _, _, email = conversation_user

    with TestClient(app) as client:
        login(client, email)
        response = client.get(f"/conversations/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Conversation not found"}


def test_end_conversation_is_idempotent_and_prevents_new_messages(
    conversation_user: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    organization_id, _, email = conversation_user

    with TestClient(app) as client:
        login(client, email)
        conversation_id = create_conversation(client, organization_id)
        first_end_response = client.post(f"/conversations/{conversation_id}/end")
        repeated_end_response = client.post(f"/conversations/{conversation_id}/end")
        detail_response = client.get(f"/conversations/{conversation_id}")
        message_response = client.post(
            f"/conversations/{conversation_id}/messages",
            json=message_request(),
        )

    assert first_end_response.status_code == 200
    assert repeated_end_response.status_code == 200
    assert first_end_response.json()["status"] == "ended"
    assert repeated_end_response.json() == first_end_response.json()
    assert detail_response.status_code == 200
    assert detail_response.json()["status"] == "ended"
    assert message_response.status_code == 409
    assert message_response.json() == {"detail": "Conversation has ended"}


def test_end_conversation_requires_authentication() -> None:
    with TestClient(app) as client:
        response = client.post(f"/conversations/{uuid.uuid4()}/end")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_end_conversation_rejects_non_member(
    conversation_user: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    _, user_id, email = conversation_user
    other_organization_id = uuid.uuid4()

    with SessionLocal() as db:
        db.add(
            Organization(
                id=other_organization_id,
                name="End Conversation Other Organization",
                slug=f"end-conversation-other-{uuid.uuid4()}",
            )
        )
        db.flush()
        conversation = Conversation(
            organization_id=other_organization_id,
            created_by_user_id=user_id,
        )
        db.add(conversation)
        db.commit()
        conversation_id = conversation.id

    try:
        with TestClient(app) as client:
            login(client, email)
            response = client.post(f"/conversations/{conversation_id}/end")

        assert response.status_code == 403
        assert response.json() == {"detail": "Not a member of this organization"}
    finally:
        with SessionLocal() as db:
            db.execute(
                delete(Organization).where(Organization.id == other_organization_id)
            )
            db.commit()


def test_end_conversation_returns_not_found_for_unknown_conversation(
    conversation_user: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    _, _, email = conversation_user

    with TestClient(app) as client:
        login(client, email)
        response = client.post(f"/conversations/{uuid.uuid4()}/end")

    assert response.status_code == 404
    assert response.json() == {"detail": "Conversation not found"}


def test_add_messages_reuses_speaker_and_assigns_sequence_numbers(
    conversation_user: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    organization_id, _, email = conversation_user

    with TestClient(app) as client:
        login(client, email)
        conversation_id = create_conversation(client, organization_id)
        first_response = client.post(
            f"/conversations/{conversation_id}/messages",
            json=message_request(),
        )
        second_response = client.post(
            f"/conversations/{conversation_id}/messages",
            json=message_request(
                speaker_label="speaker_2",
                side="sales_rep",
                content="現在はどのように管理されていますか？",
            ),
        )
        third_response = client.post(
            f"/conversations/{conversation_id}/messages",
            json=message_request(content="スプレッドシートで管理しています。"),
        )

    assert [
        first_response.status_code,
        second_response.status_code,
        third_response.status_code,
    ] == [201, 201, 201]

    first_body = first_response.json()
    second_body = second_response.json()
    third_body = third_response.json()
    assert [
        first_body["sequence_number"],
        second_body["sequence_number"],
        third_body["sequence_number"],
    ] == [1, 2, 3]
    assert first_body["participant_id"] == third_body["participant_id"]
    assert first_body["participant_id"] != second_body["participant_id"]

    with SessionLocal() as db:
        participants = db.scalars(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conversation_id
            )
        ).all()
        messages = db.scalars(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.sequence_number)
        ).all()

    assert len(participants) == 2
    assert [message.sequence_number for message in messages] == [1, 2, 3]
    assert [message.content for message in messages] == [
        "案件管理に時間がかかっています。",
        "現在はどのように管理されていますか？",
        "スプレッドシートで管理しています。",
    ]


def test_concurrent_messages_receive_unique_sequence_numbers(
    conversation_user: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    organization_id, _, email = conversation_user

    with TestClient(app) as client:
        login(client, email)
        conversation_id = create_conversation(client, organization_id)

    request_barrier = Barrier(2)

    def add_message(speaker_label: str) -> tuple[int, int]:
        with TestClient(app) as client:
            login(client, email)
            request_barrier.wait()
            response = client.post(
                f"/conversations/{conversation_id}/messages",
                json=message_request(speaker_label=speaker_label),
            )
        return response.status_code, response.json()["sequence_number"]

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(add_message, ["speaker_1", "speaker_2"]))

    assert [status_code for status_code, _ in results] == [201, 201]
    assert sorted(sequence_number for _, sequence_number in results) == [1, 2]


def test_add_message_requires_authentication() -> None:
    with TestClient(app) as client:
        response = client.post(
            f"/conversations/{uuid.uuid4()}/messages",
            json=message_request(),
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_add_message_rejects_non_member(
    conversation_user: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    _, user_id, email = conversation_user
    other_organization_id = uuid.uuid4()

    with SessionLocal() as db:
        db.add(
            Organization(
                id=other_organization_id,
                name="Message API Other Organization",
                slug=f"message-api-other-{uuid.uuid4()}",
            )
        )
        db.flush()
        conversation = Conversation(
            organization_id=other_organization_id,
            created_by_user_id=user_id,
        )
        db.add(conversation)
        db.commit()
        conversation_id = conversation.id

    try:
        with TestClient(app) as client:
            login(client, email)
            response = client.post(
                f"/conversations/{conversation_id}/messages",
                json=message_request(),
            )

        assert response.status_code == 403
        assert response.json() == {"detail": "Not a member of this organization"}
    finally:
        with SessionLocal() as db:
            db.execute(
                delete(Organization).where(Organization.id == other_organization_id)
            )
            db.commit()


def test_add_message_returns_not_found_for_unknown_conversation(
    conversation_user: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    _, _, email = conversation_user

    with TestClient(app) as client:
        login(client, email)
        response = client.post(
            f"/conversations/{uuid.uuid4()}/messages",
            json=message_request(),
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Conversation not found"}


def test_add_message_rejects_ended_conversation(
    conversation_user: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    organization_id, _, email = conversation_user

    with TestClient(app) as client:
        login(client, email)
        conversation_id = create_conversation(client, organization_id)
        with SessionLocal() as db:
            conversation = db.get(Conversation, conversation_id)
            assert conversation is not None
            conversation.status = ConversationStatus.ENDED
            db.commit()

        response = client.post(
            f"/conversations/{conversation_id}/messages",
            json=message_request(),
        )

    assert response.status_code == 409
    assert response.json() == {"detail": "Conversation has ended"}


def test_add_message_rejects_changing_an_existing_speaker_side(
    conversation_user: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    organization_id, _, email = conversation_user

    with TestClient(app) as client:
        login(client, email)
        conversation_id = create_conversation(client, organization_id)
        first_response = client.post(
            f"/conversations/{conversation_id}/messages",
            json=message_request(),
        )
        conflict_response = client.post(
            f"/conversations/{conversation_id}/messages",
            json=message_request(side="sales_rep"),
        )

    assert first_response.status_code == 201
    assert conflict_response.status_code == 409
    assert conflict_response.json() == {
        "detail": "Speaker label is already assigned to a different side"
    }

    with SessionLocal() as db:
        message_count = db.scalar(
            select(func.count())
            .select_from(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
        )
    assert message_count == 1


def test_add_message_rejects_empty_content_without_saving(
    conversation_user: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    organization_id, _, email = conversation_user

    with TestClient(app) as client:
        login(client, email)
        conversation_id = create_conversation(client, organization_id)
        response = client.post(
            f"/conversations/{conversation_id}/messages",
            json=message_request(content="   "),
        )

    assert response.status_code == 422

    with SessionLocal() as db:
        message_count = db.scalar(
            select(func.count())
            .select_from(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
        )
    assert message_count == 0


def test_confirmation_items_authorization_and_versioning(
    conversation_user: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    organization_id, _, email = conversation_user
    with TestClient(app) as client:
        assert (
            client.get(f"/conversations/{uuid.uuid4()}/confirmation-items").status_code
            == 401
        )
        login(client, email)
        conversation_id = create_conversation(client, organization_id)
        created = client.post(
            f"/conversations/{conversation_id}/confirmation-items",
            json={"content": "導入時期を確認する"},
        )
        assert created.status_code == 201
        item = created.json()
        assert item["status"] == "open" and item["version"] == 1
        duplicate = client.post(
            f"/conversations/{conversation_id}/confirmation-items",
            json={"content": "  導入時期を確認する  "},
        )
        assert duplicate.status_code == 201
        assert duplicate.json()["id"] == item["id"]
        changed = client.patch(
            f"/conversations/{conversation_id}/confirmation-items/{item['id']}",
            json={"status": "confirmed", "expected_version": 1},
        )
        assert changed.status_code == 200
        assert changed.json()["version"] == 2
        assert changed.json()["confirmation_source"] == "manual"
        assert (
            client.patch(
                f"/conversations/{conversation_id}/confirmation-items/{item['id']}",
                json={"status": "open", "expected_version": 1},
            ).status_code
            == 409
        )
        assert (
            client.get(f"/conversations/{conversation_id}/confirmation-items").json()[
                "items"
            ][0]["status"]
            == "confirmed"
        )
