import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from signal_api.models import UserSession
from signal_api.security import generate_session_token, hash_session_token

SESSION_DURATION = timedelta(days=30)


@dataclass(frozen=True)
class CreatedSession:
    token: str
    expires_at: datetime


@dataclass(frozen=True)
class ValidSession:
    id: uuid.UUID
    user_id: uuid.UUID
    expires_at: datetime


def create_session(db: Session, user_id: uuid.UUID) -> CreatedSession:
    token = generate_session_token()
    expires_at = datetime.now(UTC) + SESSION_DURATION

    db.add(
        UserSession(
            user_id=user_id,
            token_hash=hash_session_token(token),
            expires_at=expires_at,
        )
    )
    db.commit()

    return CreatedSession(token=token, expires_at=expires_at)


def get_valid_session(db: Session, token: str) -> ValidSession | None:
    session = db.scalar(
        select(UserSession).where(
            UserSession.token_hash == hash_session_token(token),
            UserSession.expires_at > datetime.now(UTC),
        )
    )

    if session is None:
        return None

    return ValidSession(
        id=session.id,
        user_id=session.user_id,
        expires_at=session.expires_at,
    )


def delete_session(db: Session, token: str) -> None:
    db.execute(
        delete(UserSession).where(UserSession.token_hash == hash_session_token(token))
    )
    db.commit()
