from __future__ import annotations

from uuid import uuid4

from aep.modules.auth.domain.models import User, UserStatus


def test_user_defaults_to_active_status_and_no_roles() -> None:
    user = User(
        id=uuid4(),
        email="a@example.com",
        display_name="A",
        auth_provider="github",
        auth_subject="123",
    )

    assert user.status == UserStatus.ACTIVE
    assert user.roles == []
