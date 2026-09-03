import base64
import hashlib
import secrets

import bcrypt

SESSION_TOKEN_BYTES = 32


def generate_session_token() -> str:
    token_bytes = secrets.token_bytes(SESSION_TOKEN_BYTES)
    return base64.urlsafe_b64encode(token_bytes).rstrip(b"=").decode("ascii")


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode(
        "utf-8"
    )
