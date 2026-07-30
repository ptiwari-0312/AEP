from __future__ import annotations

from uuid import uuid4

import pytest

from aep.core.config import get_settings
from aep.core.db import Base, get_engine, get_session_factory
from aep.modules.prompt_library.domain.models import PromptTemplate
from aep.modules.prompt_library.repository.prompt_template_repository import (
    PromptTemplateRepository,
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
async def repository():
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield PromptTemplateRepository(session)


async def test_add_and_get_by_id_round_trips(repository: PromptTemplateRepository) -> None:
    template = PromptTemplate(id=uuid4(), name="coding-agent-system-prompt", owner_user_id=uuid4())

    created = await repository.add(template)
    fetched = await repository.get_by_id(created.id)

    assert fetched is not None
    assert fetched.name == "coding-agent-system-prompt"


async def test_get_by_name(repository: PromptTemplateRepository) -> None:
    await repository.add(PromptTemplate(id=uuid4(), name="a-prompt", owner_user_id=uuid4()))

    found = await repository.get_by_name("a-prompt")
    missing = await repository.get_by_name("missing-prompt")

    assert found is not None
    assert missing is None


async def test_list_paginates_with_offset(repository: PromptTemplateRepository) -> None:
    for i in range(5):
        await repository.add(PromptTemplate(id=uuid4(), name=f"prompt-{i}", owner_user_id=uuid4()))

    first_page, total = await repository.list(limit=2, offset=0)
    second_page, _ = await repository.list(limit=2, offset=2)

    assert total == 5
    assert len(first_page) == 2
    assert len(second_page) == 2
    assert {t.id for t in first_page}.isdisjoint({t.id for t in second_page})
