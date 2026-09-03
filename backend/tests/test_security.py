import re

import bcrypt

from signal_api.security import (
    generate_session_token,
    hash_password,
    hash_session_token,
)


def test_session_token_is_random_and_url_safe() -> None:
    first = generate_session_token()
    second = generate_session_token()

    assert first != second
    assert len(first) == 43
    assert re.fullmatch(r"[A-Za-z0-9_-]+", first)


def test_session_token_hash_is_deterministic_sha256_hex() -> None:
    token = generate_session_token()
    token_hash = hash_session_token(token)

    assert len(token_hash) == 64
    assert token_hash == hash_session_token(token)
    assert token_hash != token


def test_password_is_stored_as_a_bcrypt_hash() -> None:
    password = "demo-password"
    password_hash = hash_password(password)

    assert password_hash != password
    assert bcrypt.checkpw(password.encode(), password_hash.encode())
