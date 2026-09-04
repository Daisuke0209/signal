import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from signal_api.database import SessionLocal
from signal_api.main import app
from signal_api.models import User, UserSession
from signal_api.security import hash_password, hash_session_token

TEST_PASSWORD = "integration-test-password"


@pytest.fixture
def login_user() -> Iterator[tuple[uuid.UUID, str]]:
    email = f"login-test-{uuid.uuid4()}@signal.local"

    with SessionLocal() as db:
        user = User(
            name="Login Test User",
            email=email,
            password_hash=hash_password(TEST_PASSWORD),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id

    try:
        yield user_id, email
    finally:
        with SessionLocal() as db:
            # sessionsは外部キーのON DELETE CASCADEで一緒に削除される
            db.execute(delete(User).where(User.id == user_id))
            db.commit()


def test_login_creates_session_and_sets_cookie(
    login_user: tuple[uuid.UUID, str],
) -> None:
    user_id, email = login_user

    with TestClient(app) as client:
        response = client.post(
            "/auth/login",
            json={
                "email": email,
                "password": TEST_PASSWORD,
            },
        )

    assert response.status_code == 204
    assert response.content == b""

    token = response.cookies.get("signal_session")
    assert token is not None

    set_cookie = response.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "path=/" in set_cookie

    with SessionLocal() as db:
        stored_session = db.scalar(
            select(UserSession).where(UserSession.user_id == user_id)
        )

    assert stored_session is not None
    assert stored_session.token_hash != token
    assert stored_session.token_hash == hash_session_token(token)


def test_login_rejects_invalid_credentials_without_creating_session(
    login_user: tuple[uuid.UUID, str],
) -> None:
    user_id, email = login_user

    with TestClient(app) as client:
        wrong_password_response = client.post(
            "/auth/login",
            json={
                "email": email,
                "password": "wrong-password",
            },
        )
        unknown_user_response = client.post(
            "/auth/login",
            json={
                "email": f"unknown-{uuid.uuid4()}@signal.local",
                "password": TEST_PASSWORD,
            },
        )

    for response in (wrong_password_response, unknown_user_response):
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid email or password"}
        assert "signal_session" not in response.cookies
        assert "set-cookie" not in response.headers

    with SessionLocal() as db:
        session_count = db.scalar(
            select(func.count())
            .select_from(UserSession)
            .where(UserSession.user_id == user_id)
        )

    assert session_count == 0


def test_get_me_returns_authenticated_user(
    login_user: tuple[uuid.UUID, str],
) -> None:
    user_id, email = login_user

    with TestClient(app) as client:
        login_response = client.post(
            "/auth/login",
            json={
                "email": email,
                "password": TEST_PASSWORD,
            },
        )
        response = client.get("/auth/me")

    assert login_response.status_code == 204
    assert response.status_code == 200
    assert response.json() == {
        "id": str(user_id),
        "name": "Login Test User",
        "email": email,
    }


def test_get_me_rejects_missing_cookie() -> None:
    with TestClient(app) as client:
        response = client.get("/auth/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_get_me_rejects_invalid_session_token() -> None:
    with TestClient(app) as client:
        client.cookies.set("signal_session", "invalid-token")
        response = client.get("/auth/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_logout_deletes_session_and_cookie(
    login_user: tuple[uuid.UUID, str],
) -> None:
    user_id, email = login_user

    with TestClient(app) as client:
        login_response = client.post(
            "/auth/login",
            json={
                "email": email,
                "password": TEST_PASSWORD,
            },
        )
        token = login_response.cookies.get("signal_session")

        logout_response = client.post("/auth/logout")
        me_response = client.get("/auth/me")

    assert login_response.status_code == 204
    assert token is not None
    assert logout_response.status_code == 204
    assert logout_response.content == b""

    set_cookie = logout_response.headers["set-cookie"].lower()
    assert "signal_session=" in set_cookie
    assert "max-age=0" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "path=/" in set_cookie

    with SessionLocal() as db:
        stored_session = db.scalar(
            select(UserSession).where(UserSession.user_id == user_id)
        )

    assert stored_session is None
    assert me_response.status_code == 401
    assert me_response.json() == {"detail": "Authentication required"}


def test_logout_without_cookie_is_idempotent() -> None:
    with TestClient(app) as client:
        first_response = client.post("/auth/logout")
        second_response = client.post("/auth/logout")

    assert first_response.status_code == 204
    assert second_response.status_code == 204
    assert "max-age=0" in first_response.headers["set-cookie"].lower()
    assert "max-age=0" in second_response.headers["set-cookie"].lower()


def test_logout_with_invalid_session_token_is_idempotent() -> None:
    with TestClient(app) as client:
        client.cookies.set("signal_session", "invalid-token")
        response = client.post("/auth/logout")

    assert response.status_code == 204
    assert "max-age=0" in response.headers["set-cookie"].lower()
