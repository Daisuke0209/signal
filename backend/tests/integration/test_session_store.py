import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from signal_api.database import SessionLocal
from signal_api.models import User, UserSession
from signal_api.security import generate_session_token, hash_session_token
from signal_api.session_store import (
    create_session,
    delete_session,
    get_valid_session,
)


def test_session_lifecycle_uses_only_the_token_hash() -> None:
    with SessionLocal() as db:
        user = User(
            name="Session Test User",
            email=f"session-test-{uuid.uuid4()}@signal.local",
            password_hash="not-used-in-this-test",
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        token: str | None = None
        try:
            created = create_session(db, user.id)
            token = created.token

            stored = db.scalar(
                select(UserSession).where(UserSession.user_id == user.id)
            )
            assert stored is not None
            assert stored.token_hash != token
            assert stored.token_hash == hash_session_token(token)

            remaining = created.expires_at - datetime.now(UTC)
            assert timedelta(days=29) < remaining <= timedelta(days=30)

            valid = get_valid_session(db, token)
            assert valid is not None
            assert valid.id == stored.id
            assert valid.user_id == user.id

            delete_session(db, token)
            assert get_valid_session(db, token) is None
            assert get_valid_session(db, "unknown-token") is None
        finally:
            if token is not None:
                delete_session(db, token)
            db.execute(delete(User).where(User.id == user.id))
            db.commit()


def test_expired_session_is_rejected() -> None:
    with SessionLocal() as db:
        user = User(
            name="Expired Session Test User",
            email=f"expired-session-test-{uuid.uuid4()}@signal.local",
            password_hash="not-used-in-this-test",
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        token = generate_session_token()
        db.add(
            UserSession(
                user_id=user.id,
                token_hash=hash_session_token(token),
                expires_at=datetime.now(UTC) - timedelta(seconds=1),
            )
        )
        db.commit()

        try:
            assert get_valid_session(db, token) is None
        finally:
            db.execute(delete(User).where(User.id == user.id))
            db.commit()
