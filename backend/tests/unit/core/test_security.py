from __future__ import annotations

import time
from uuid import uuid4

import pytest
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt

from aep.core.config import Settings
from aep.core.errors import ForbiddenError, UnauthorizedError
from aep.core.security import (
    AuthenticatedUser,
    create_access_token,
    decode_access_token,
    get_current_user,
    require_role,
)

_SETTINGS = Settings(jwt_secret_key="test-secret", jwt_algorithm="HS256", _env_file=None)


def test_create_and_decode_access_token_round_trips() -> None:
    user_id = uuid4()
    token, expires_in = create_access_token(user_id=user_id, roles=["engineer"], settings=_SETTINGS)

    user = decode_access_token(token, settings=_SETTINGS)

    assert user.user_id == user_id
    assert user.roles == ["engineer"]
    assert expires_in == _SETTINGS.jwt_access_token_expire_minutes * 60


def test_decode_rejects_expired_token() -> None:
    expired_claims = {
        "sub": str(uuid4()),
        "roles": ["viewer"],
        "type": "access",
        "iat": int(time.time()) - 120,
        "exp": int(time.time()) - 60,
    }
    token = jwt.encode(expired_claims, _SETTINGS.jwt_secret_key, algorithm=_SETTINGS.jwt_algorithm)

    with pytest.raises(UnauthorizedError, match="expired"):
        decode_access_token(token, settings=_SETTINGS)


def test_decode_rejects_wrong_signature() -> None:
    token, _ = create_access_token(user_id=uuid4(), roles=["viewer"], settings=_SETTINGS)
    other_settings = Settings(jwt_secret_key="different-secret", _env_file=None)

    with pytest.raises(UnauthorizedError, match="invalid"):
        decode_access_token(token, settings=other_settings)


def test_decode_rejects_non_access_token_type() -> None:
    claims = {
        "sub": str(uuid4()),
        "roles": [],
        "type": "refresh",
        "exp": int(time.time()) + 60,
    }
    token = jwt.encode(claims, _SETTINGS.jwt_secret_key, algorithm=_SETTINGS.jwt_algorithm)

    with pytest.raises(UnauthorizedError, match="not an access token"):
        decode_access_token(token, settings=_SETTINGS)


async def test_get_current_user_raises_when_no_credentials() -> None:
    with pytest.raises(UnauthorizedError, match="missing bearer token"):
        await get_current_user(credentials=None)


def test_has_role_direct_match() -> None:
    user = AuthenticatedUser(user_id=uuid4(), roles=["engineer"])
    assert user.has_role("engineer")
    assert not user.has_role("admin")


def test_has_role_admin_is_additive() -> None:
    user = AuthenticatedUser(user_id=uuid4(), roles=["admin"])
    assert user.has_role("viewer")
    assert user.has_role("engineer")
    assert user.has_role("admin")


async def test_require_role_allows_matching_role() -> None:
    dependency = require_role("engineer")
    user = AuthenticatedUser(user_id=uuid4(), roles=["engineer"])

    result = await dependency(user=user)

    assert result is user


async def test_require_role_allows_admin_override() -> None:
    dependency = require_role("admin")
    user = AuthenticatedUser(user_id=uuid4(), roles=["admin"])

    result = await dependency(user=user)

    assert result is user


async def test_require_role_rejects_insufficient_role() -> None:
    dependency = require_role("admin")
    user = AuthenticatedUser(user_id=uuid4(), roles=["viewer"])

    with pytest.raises(ForbiddenError, match="admin"):
        await dependency(user=user)


def test_bearer_credentials_are_accepted_end_to_end() -> None:
    user_id = uuid4()
    token, _ = create_access_token(user_id=user_id, roles=["viewer"], settings=_SETTINGS)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    user = decode_access_token(credentials.credentials, settings=_SETTINGS)

    assert user.user_id == user_id
