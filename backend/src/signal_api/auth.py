from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from signal_api.database import get_db_session
from signal_api.models import User
from signal_api.security import verify_password
from signal_api.session_store import create_session

SESSION_COOKIE_NAME = "signal_session"

router = APIRouter(prefix="/auth", tags=["auth"])

DatabaseSession = Annotated[Session, Depends(get_db_session)]


class LoginRequest(BaseModel):
    email: str
    password: SecretStr


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
