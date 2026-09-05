import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import delete, func, select

from signal_api import documents
from signal_api.config import get_settings
from signal_api.database import SessionLocal
from signal_api.main import app
from signal_api.models import Document, DocumentPage, Membership, Organization, User
from signal_api.security import hash_password

PASSWORD = "document-api-test-password"


@pytest.fixture
def document_user() -> Iterator[tuple[uuid.UUID, str]]:
    marker = uuid.uuid4()
    with SessionLocal() as db:
        organization = Organization(name="Documents", slug=f"documents-{marker}")
        user = User(
            name="Documents",
            email=f"documents-{marker}@signal.local",
            password_hash=hash_password(PASSWORD),
        )
        db.add_all([organization, user])
        db.flush()
        db.add(Membership(organization_id=organization.id, user_id=user.id))
        db.commit()
        organization_id, email = organization.id, user.email
    try:
        yield organization_id, email
    finally:
        with SessionLocal() as db:
            db.execute(delete(Organization).where(Organization.id == organization_id))
            db.commit()


@pytest.fixture
def storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    settings = get_settings().model_copy(
        update={"document_storage_dir": tmp_path, "document_max_size_bytes": 32}
    )
    monkeypatch.setattr(documents, "get_settings", lambda: settings)
    return tmp_path


def upload(
    client: TestClient, organization_id: uuid.UUID, content: bytes = b"%PDF-1.4\n"
) -> Response:
    return cast(
        Response,
        client.post(
            "/documents",
            data={"organization_id": str(organization_id)},
            files={"file": ("guide.pdf", content, "application/pdf")},
        ),
    )


def test_document_upload_requires_authentication(
    document_user: tuple[uuid.UUID, str], storage: Path
) -> None:
    organization_id, _ = document_user
    with TestClient(app) as client:
        response = upload(client, organization_id)
    assert response.status_code == 401
    assert list(storage.iterdir()) == []


def test_document_upload_persists_authorized_pdf(
    document_user: tuple[uuid.UUID, str], storage: Path
) -> None:
    organization_id, email = document_user
    with TestClient(app) as client:
        assert (
            client.post(
                "/auth/login", json={"email": email, "password": PASSWORD}
            ).status_code
            == 204
        )
        response = upload(client, organization_id)
    assert response.status_code == 201
    body = response.json()
    assert body["organization_id"] == str(organization_id)
    assert body["processing_status"] == "pending"
    assert not (storage / "guide.pdf").exists()
    assert len(list(storage.iterdir())) == 1
    with SessionLocal() as db:
        document = db.scalar(
            select(Document).where(Document.id == uuid.UUID(body["id"]))
        )
    assert document is not None
    assert document.organization_id == organization_id


def test_list_documents_is_organization_scoped(
    document_user: tuple[uuid.UUID, str],
) -> None:
    organization_id, email = document_user
    with TestClient(app) as client:
        assert (
            client.get(f"/documents?organization_id={organization_id}").status_code
            == 401
        )
        client.post("/auth/login", json={"email": email, "password": PASSWORD})
        response = client.get(f"/documents?organization_id={organization_id}")
        denied = client.get(f"/documents?organization_id={uuid.uuid4()}")
    assert response.status_code == 200
    assert response.json() == []
    assert denied.status_code == 403


def test_list_documents_returns_metadata_newest_first(
    document_user: tuple[uuid.UUID, str],
) -> None:
    organization_id, email = document_user
    with SessionLocal() as db:
        user_id = db.scalar(select(User.id).where(User.email == email))
        other = Organization(name="Other", slug=f"other-{uuid.uuid4()}")
        db.add(other)
        db.flush()
        older = datetime.now(UTC) - timedelta(minutes=1)
        db.add_all(
            [
                Document(
                    organization_id=organization_id,
                    uploaded_by_user_id=user_id,
                    filename="old.pdf",
                    content_type="application/pdf",
                    byte_size=1,
                    storage_key=str(uuid.uuid4()),
                    created_at=older,
                ),
                Document(
                    organization_id=other.id,
                    uploaded_by_user_id=user_id,
                    filename="other.pdf",
                    content_type="application/pdf",
                    byte_size=1,
                    storage_key=str(uuid.uuid4()),
                ),
                Document(
                    organization_id=organization_id,
                    uploaded_by_user_id=user_id,
                    filename="failed.pdf",
                    content_type="application/pdf",
                    byte_size=1,
                    storage_key=str(uuid.uuid4()),
                    processing_status="failed",
                    processing_error="PDF extraction failed",
                ),
            ]
        )
        db.commit()
    with TestClient(app) as client:
        client.post("/auth/login", json={"email": email, "password": PASSWORD})
        response = client.get(f"/documents?organization_id={organization_id}")
    assert response.status_code == 200
    rows = response.json()
    assert [row["filename"] for row in rows] == ["failed.pdf", "old.pdf"]
    assert rows[0]["processing_error"] == "PDF extraction failed"
    assert rows[0]["uploaded_by_name"] == "Documents"


def test_extract_document_persists_multipage_text(
    document_user: tuple[uuid.UUID, str], storage: Path
) -> None:
    organization_id, email = document_user
    fixture = Path(__file__).parents[1] / "fixtures" / "signal-demo-product.pdf"
    storage_key = str(uuid.uuid4())
    (storage / storage_key).write_bytes(fixture.read_bytes())
    with SessionLocal() as db:
        user_id = db.scalar(select(User.id).where(User.email == email))
        document = Document(
            organization_id=organization_id,
            uploaded_by_user_id=user_id,
            filename="sample.pdf",
            content_type="application/pdf",
            byte_size=fixture.stat().st_size,
            storage_key=storage_key,
        )
        db.add(document)
        db.commit()
        document_id = document.id
    with TestClient(app) as client:
        client.post("/auth/login", json={"email": email, "password": PASSWORD})
        response = client.post(f"/documents/{document_id}/extract")
    assert response.status_code == 200
    assert response.json()["processing_status"] == "ready"
    with SessionLocal() as db:
        pages = db.scalars(
            select(DocumentPage)
            .where(DocumentPage.document_id == document_id)
            .order_by(DocumentPage.page_number)
        ).all()
    assert [page.page_number for page in pages] == [1, 2, 3]
    assert any(page.content.strip() for page in pages)
    with TestClient(app) as client:
        client.post("/auth/login", json={"email": email, "password": PASSWORD})
        assert client.post(f"/documents/{document_id}/extract").status_code == 200
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(DocumentPage)
                .where(DocumentPage.document_id == document_id)
            )
            == 3
        )


def test_document_upload_rejects_authenticated_nonmember(
    document_user: tuple[uuid.UUID, str], storage: Path
) -> None:
    _, email = document_user
    other_id = uuid.uuid4()
    with SessionLocal() as db:
        db.add(Organization(id=other_id, name="Other", slug=f"other-{other_id}"))
        db.commit()
    try:
        with TestClient(app) as client:
            client.post("/auth/login", json={"email": email, "password": PASSWORD})
            response = upload(client, other_id)
        assert response.status_code == 403
        assert list(storage.iterdir()) == []
        with SessionLocal() as db:
            assert (
                db.scalar(select(Document).where(Document.organization_id == other_id))
                is None
            )
    finally:
        with SessionLocal() as db:
            db.execute(delete(Organization).where(Organization.id == other_id))
            db.commit()


def test_document_upload_enforces_organization_limit(
    document_user: tuple[uuid.UUID, str], storage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    organization_id, email = document_user
    settings = get_settings().model_copy(
        update={
            "document_storage_dir": storage,
            "document_max_count_per_organization": 1,
        }
    )
    monkeypatch.setattr(documents, "get_settings", lambda: settings)
    with SessionLocal() as db:
        db.add(
            Document(
                organization_id=organization_id,
                uploaded_by_user_id=db.scalar(
                    select(User.id).where(User.email == email)
                ),
                filename="existing.pdf",
                content_type="application/pdf",
                byte_size=1,
                storage_key=str(uuid.uuid4()),
            )
        )
        db.commit()
    with TestClient(app) as client:
        client.post("/auth/login", json={"email": email, "password": PASSWORD})
        response = upload(client, organization_id)
    assert response.status_code == 422
    assert list(storage.iterdir()) == []
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(Document)
                .where(Document.organization_id == organization_id)
            )
            == 1
        )


@pytest.mark.parametrize(
    "content,content_type",
    [
        (b"", "application/pdf"),
        (b"not pdf", "application/pdf"),
        (b"%PDF-1.4\n", "text/plain"),
        (b"%PDF-" + b"x" * 40, "application/pdf"),
    ],
)
def test_document_upload_rejects_invalid_input_without_storage(
    document_user: tuple[uuid.UUID, str],
    storage: Path,
    content: bytes,
    content_type: str,
) -> None:
    organization_id, email = document_user
    with TestClient(app) as client:
        client.post("/auth/login", json={"email": email, "password": PASSWORD})
        response = client.post(
            "/documents",
            data={"organization_id": str(organization_id)},
            files={"file": ("guide.pdf", content, content_type)},
        )
    assert response.status_code == 422
    assert list(storage.iterdir()) == []
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(Document).where(Document.organization_id == organization_id)
            )
            is None
        )


def test_search_documents_scopes_and_ranks_japanese_pages(
    document_user: tuple[uuid.UUID, str],
) -> None:
    organization_id, email = document_user
    other_organization_id = uuid.uuid4()
    with SessionLocal() as db:
        user_id = db.scalar(select(User.id).where(User.email == email))
        assert user_id is not None
        db.add(
            Organization(
                id=other_organization_id,
                name="Other organization",
                slug=f"other-{other_organization_id}",
            )
        )
        db.flush()
        ready = Document(
            organization_id=organization_id,
            uploaded_by_user_id=user_id,
            filename="guide.pdf",
            content_type="application/pdf",
            byte_size=1,
            storage_key=str(uuid.uuid4()),
            processing_status="ready",
        )
        pending = Document(
            organization_id=organization_id,
            uploaded_by_user_id=user_id,
            filename="pending.pdf",
            content_type="application/pdf",
            byte_size=1,
            storage_key=str(uuid.uuid4()),
        )
        other_ready = Document(
            organization_id=other_organization_id,
            uploaded_by_user_id=user_id,
            filename="other-guide.pdf",
            content_type="application/pdf",
            byte_size=1,
            storage_key=str(uuid.uuid4()),
            processing_status="ready",
        )
        db.add_all([ready, pending, other_ready])
        db.flush()
        db.add_all(
            [
                DocumentPage(
                    document_id=ready.id, page_number=1, content="営業支援の料金"
                ),
                DocumentPage(
                    document_id=ready.id, page_number=2, content="料金と料金の詳細"
                ),
                DocumentPage(document_id=other_ready.id, page_number=1, content="料金"),
            ]
        )
        db.commit()
        ready_id = ready.id
        other_ready_id = other_ready.id
    try:
        with TestClient(app) as client:
            assert (
                client.post(
                    "/documents/search",
                    json={"organization_id": str(organization_id), "query": "料金"},
                ).status_code
                == 401
            )
            client.post("/auth/login", json={"email": email, "password": PASSWORD})
            response = client.post(
                "/documents/search",
                json={"organization_id": str(organization_id), "query": "料金"},
            )
            empty = client.post(
                "/documents/search",
                json={
                    "organization_id": str(organization_id),
                    "query": "料金",
                    "document_ids": [],
                },
            )
            denied = client.post(
                "/documents/search",
                json={"organization_id": str(other_organization_id), "query": "料金"},
            )
            selected = client.post(
                "/documents/search",
                json={
                    "organization_id": str(organization_id),
                    "query": "料金",
                    "document_ids": [str(ready_id), str(other_ready_id)],
                },
            )
        assert [row["page_number"] for row in response.json()] == [2, 1]
        assert all(row["document_id"] == str(ready_id) for row in response.json())
        assert empty.json() == []
        assert denied.status_code == 403
        assert all(row["document_id"] == str(ready_id) for row in selected.json())
    finally:
        with SessionLocal() as db:
            other_organization = db.get(Organization, other_organization_id)
            if other_organization is not None:
                db.delete(other_organization)
                db.commit()


def test_extract_malformed_document_has_safe_failed_state(
    document_user: tuple[uuid.UUID, str], storage: Path
) -> None:
    organization_id, email = document_user
    key = str(uuid.uuid4())
    (storage / key).write_bytes(b"%PDF-broken")
    with SessionLocal() as db:
        document = Document(
            organization_id=organization_id,
            uploaded_by_user_id=db.scalar(select(User.id).where(User.email == email)),
            filename="bad.pdf",
            content_type="application/pdf",
            byte_size=11,
            storage_key=key,
        )
        db.add(document)
        db.commit()
        document_id = document.id
    with TestClient(app) as client:
        client.post("/auth/login", json={"email": email, "password": PASSWORD})
        response = client.post(f"/documents/{document_id}/extract")
    assert response.status_code == 200
    assert response.json()["processing_status"] == "failed"
    with SessionLocal() as db:
        stored = db.get(Document, document_id)
        assert stored is not None
        assert stored.processing_error == "PDF extraction failed"
        assert (
            db.scalar(
                select(DocumentPage).where(DocumentPage.document_id == document_id)
            )
            is None
        )


def test_extract_other_organization_does_not_mutate_document(
    document_user: tuple[uuid.UUID, str], storage: Path
) -> None:
    _, email = document_user
    other_id = uuid.uuid4()
    key = str(uuid.uuid4())
    (storage / key).write_bytes(b"%PDF-broken")
    with SessionLocal() as db:
        db.add(Organization(id=other_id, name="Other", slug=f"other-{other_id}"))
        user_id = db.scalar(select(User.id).where(User.email == email))
        document = Document(
            organization_id=other_id,
            uploaded_by_user_id=user_id,
            filename="other.pdf",
            content_type="application/pdf",
            byte_size=11,
            storage_key=key,
        )
        db.add(document)
        db.commit()
        document_id = document.id
    try:
        with TestClient(app) as client:
            client.post("/auth/login", json={"email": email, "password": PASSWORD})
            assert client.post(f"/documents/{document_id}/extract").status_code == 403
        with SessionLocal() as db:
            stored = db.get(Document, document_id)
            assert stored is not None and stored.processing_status.value == "pending"
            assert (
                db.scalar(
                    select(DocumentPage).where(DocumentPage.document_id == document_id)
                )
                is None
            )
    finally:
        with SessionLocal() as db:
            db.execute(delete(Organization).where(Organization.id == other_id))
            db.commit()
