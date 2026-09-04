import uuid
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel, SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from signal_api.database import get_db_session
from signal_api.models import User
from signal_api.security import verify_password
from signal_api.session_store import create_session, delete_session, get_valid_session

SESSION_COOKIE_NAME = "signal_session"

router = APIRouter(prefix="/auth", tags=["auth"])

DatabaseSession = Annotated[Session, Depends(get_db_session)]
SessionCookie = Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)]


class LoginRequest(BaseModel):
    email: str
    password: SecretStr


class CurrentUserResponse(BaseModel):
    id: uuid.UUID
    name: str
    email: str


def authentication_required() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
    )


def get_current_user(
    db: DatabaseSession,
    session_token: SessionCookie = None,
) -> User:
    if session_token is None:
        raise authentication_required()

    valid_session = get_valid_session(db, session_token)
    if valid_session is None:
        raise authentication_required()

    user = db.get(User, valid_session.user_id)
    if user is None:
        raise authentication_required()

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


@router.post("/login", status_code=status.HTTP_204_NO_CONTENT)
def login(
    request: LoginRequest,
    response: Response,
    db: DatabaseSession,
) -> None:
    email = request.email.strip().lower()

    user = db.scalar(select(User).where(User.email == email))

    if user is None or not verify_password(
        request.password.get_secret_value(),
        user.password_hash,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    created_session = create_session(db, user.id)

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=created_session.token,
        expires=created_session.expires_at,
        httponly=True,
        secure=False,  # ローカル開発用。本番ではTrueにする
        samesite="lax",
        path="/",
    )


@router.get("/me", response_model=CurrentUserResponse)
def get_me(current_user: CurrentUser) -> CurrentUserResponse:
    return CurrentUserResponse(
        id=current_user.id,
        name=current_user.name,
        email=current_user.email,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    db: DatabaseSession,
    session_token: SessionCookie = None,
) -> None:
    if session_token is not None:
        delete_session(db, session_token)

    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        secure=False,  # ローカル開発用。本番ではTrueにする
        samesite="lax",
        path="/",
    )
