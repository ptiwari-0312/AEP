from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from aep.core.config import get_settings
from aep.core.db import Base, get_engine, get_session_factory
from aep.modules.prompt_library.domain.models import (
    PromptTemplate,
    PromptVariable,
    PromptVersion,
)
from aep.modules.prompt_library.repository.prompt_template_repository import (
    PromptTemplateRepository,
)
from aep.modules.prompt_library.repository.prompt_version_repository import (
    PromptVersionRepository,
)


@pytest.fixture(autouse=True)
async def _sqlite_backed_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("AEP_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield

    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()


@pytest.fixture
async def session():
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session


@pytest.fixture
def repository(session) -> PromptVersionRepository:
    return PromptVersionRepository(session)


@pytest.fixture
async def template_id(session) -> object:
    template = await PromptTemplateRepository(session).add(
        PromptTemplate(id=uuid4(), name="coding-agent-system-prompt", owner_user_id=uuid4())
    )
    return template.id


async def test_add_and_get_by_id_round_trips(
    repository: PromptVersionRepository, template_id
) -> None:
    version = PromptVersion(
        id=uuid4(),
        prompt_template_id=template_id,
        version_number=1,
        content="Hello {{ name }}",
        created_by=uuid4(),
        variables=[PromptVariable(name="name")],
    )

    created = await repository.add(version)
    fetched = await repository.get_by_id(created.id)

    assert fetched is not None
    assert fetched.content == "Hello {{ name }}"
    assert fetched.variables == [PromptVariable(name="name", required=True)]


async def test_get_by_template_and_version_number(
    repository: PromptVersionRepository, template_id
) -> None:
    await repository.add(
        PromptVersion(
            id=uuid4(), prompt_template_id=template_id, version_number=1, content="v1", created_by=uuid4()
        )
    )

    found = await repository.get_by_template_and_version_number(template_id, 1)
    missing = await repository.get_by_template_and_version_number(template_id, 2)

    assert found is not None
    assert missing is None


async def test_get_max_version_number_is_zero_when_none_exist(
    repository: PromptVersionRepository, template_id
) -> None:
    assert await repository.get_max_version_number(template_id) == 0


async def test_get_max_version_number_reflects_highest(
    repository: PromptVersionRepository, template_id
) -> None:
    for n in (1, 2, 3):
        await repository.add(
            PromptVersion(
                id=uuid4(), prompt_template_id=template_id, version_number=n, content=f"v{n}", created_by=uuid4()
            )
        )

    assert await repository.get_max_version_number(template_id) == 3


async def test_get_active_for_template_returns_none_when_none_active(
    repository: PromptVersionRepository, template_id
) -> None:
    await repository.add(
        PromptVersion(
            id=uuid4(), prompt_template_id=template_id, version_number=1, content="v1", created_by=uuid4()
        )
    )

    assert await repository.get_active_for_template(template_id) is None


async def test_set_active_flips_the_flag(repository: PromptVersionRepository, template_id) -> None:
    version = await repository.add(
        PromptVersion(
            id=uuid4(), prompt_template_id=template_id, version_number=1, content="v1", created_by=uuid4()
        )
    )

    activated = await repository.set_active(version.id, is_active=True)

    assert activated.is_active is True
    assert (await repository.get_active_for_template(template_id)).id == version.id


async def test_list_for_template_orders_by_version_number(
    repository: PromptVersionRepository, template_id
) -> None:
    for n in (2, 1, 3):
        await repository.add(
            PromptVersion(
                id=uuid4(), prompt_template_id=template_id, version_number=n, content=f"v{n}", created_by=uuid4()
            )
        )

    versions = await repository.list_for_template(template_id)

    assert [v.version_number for v in versions] == [1, 2, 3]


async def test_db_rejects_two_active_versions_for_the_same_template(
    repository: PromptVersionRepository, template_id, session
) -> None:
    """Bypasses the service layer's own deactivate-then-activate sequencing entirely, to prove
    the partial unique index (repository/models.py) is a real DB-level constraint, not just a
    comment — docs/architecture/09-engineering-standards.md §9's own framing of what enforces
    "at most one active version per template."
    """
    first = PromptVersion(
        id=uuid4(),
        prompt_template_id=template_id,
        version_number=1,
        content="v1",
        created_by=uuid4(),
        is_active=True,
    )
    second = PromptVersion(
        id=uuid4(),
        prompt_template_id=template_id,
        version_number=2,
        content="v2",
        created_by=uuid4(),
        is_active=True,
    )
    await repository.add(first)

    with pytest.raises(IntegrityError):
        await repository.add(second)
