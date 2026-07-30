from __future__ import annotations

from uuid import uuid4

import pytest

from aep.core.config import get_settings
from aep.core.db import Base, get_engine, get_session_factory
from aep.modules.prompt_library.domain.errors import (
    MissingRequiredVariableError,
    PromptTemplateNameExistsError,
    PromptTemplateNotFoundError,
    PromptVersionNotFoundError,
    UndeclaredVariableReferencedError,
    VersionAlreadyActiveError,
)
from aep.modules.prompt_library.domain.models import PromptVariable
from aep.modules.prompt_library.repository.prompt_template_repository import (
    PromptTemplateRepository,
)
from aep.modules.prompt_library.repository.prompt_version_repository import (
    PromptVersionRepository,
)
from aep.modules.prompt_library.services.prompt_library_service import (
    PromptLibraryService,
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
async def service():
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield PromptLibraryService(PromptTemplateRepository(session), PromptVersionRepository(session))


async def test_create_template(service: PromptLibraryService) -> None:
    template = await service.create_template(name="coding-agent-system-prompt", owner_user_id=uuid4())

    assert template.name == "coding-agent-system-prompt"


async def test_create_template_rejects_duplicate_name(service: PromptLibraryService) -> None:
    await service.create_template(name="dup", owner_user_id=uuid4())

    with pytest.raises(PromptTemplateNameExistsError):
        await service.create_template(name="dup", owner_user_id=uuid4())


async def test_get_template_raises_not_found(service: PromptLibraryService) -> None:
    with pytest.raises(PromptTemplateNotFoundError):
        await service.get_template(uuid4())


async def test_get_template_with_active_version_is_none_before_any_version(
    service: PromptLibraryService,
) -> None:
    template = await service.create_template(name="t", owner_user_id=uuid4())

    fetched, active = await service.get_template_with_active_version(template.id)

    assert fetched.id == template.id
    assert active is None


async def test_create_version_auto_increments_version_number(service: PromptLibraryService) -> None:
    template = await service.create_template(name="t", owner_user_id=uuid4())

    v1 = await service.create_version(template.id, content="v1", created_by=uuid4())
    v2 = await service.create_version(template.id, content="v2", created_by=uuid4())

    assert v1.version_number == 1
    assert v2.version_number == 2


async def test_create_version_rejects_undeclared_variable_reference(
    service: PromptLibraryService,
) -> None:
    template = await service.create_template(name="t", owner_user_id=uuid4())

    with pytest.raises(UndeclaredVariableReferencedError):
        await service.create_version(template.id, content="Hello {{ name }}", created_by=uuid4())


async def test_create_version_raises_when_template_missing(service: PromptLibraryService) -> None:
    with pytest.raises(PromptTemplateNotFoundError):
        await service.create_version(uuid4(), content="v1", created_by=uuid4())


async def test_create_version_with_activate_true_makes_it_active(
    service: PromptLibraryService,
) -> None:
    template = await service.create_template(name="t", owner_user_id=uuid4())

    version = await service.create_version(
        template.id, content="v1", created_by=uuid4(), activate=True
    )

    assert version.is_active is True
    _template, active = await service.get_template_with_active_version(template.id)
    assert active is not None
    assert active.id == version.id


async def test_activating_a_new_version_deactivates_the_previous_one(
    service: PromptLibraryService,
) -> None:
    template = await service.create_template(name="t", owner_user_id=uuid4())
    v1 = await service.create_version(template.id, content="v1", created_by=uuid4(), activate=True)
    await service.create_version(template.id, content="v2", created_by=uuid4())

    v2_activated = await service.activate_version(template.id, 2)

    v1_refetched = await service.get_version(template.id, v1.version_number)
    assert v1_refetched.is_active is False
    assert v2_activated.is_active is True


async def test_activate_version_rejects_already_active(service: PromptLibraryService) -> None:
    template = await service.create_template(name="t", owner_user_id=uuid4())
    await service.create_version(template.id, content="v1", created_by=uuid4(), activate=True)

    with pytest.raises(VersionAlreadyActiveError):
        await service.activate_version(template.id, 1)


async def test_activate_version_raises_when_version_missing(service: PromptLibraryService) -> None:
    template = await service.create_template(name="t", owner_user_id=uuid4())

    with pytest.raises(PromptVersionNotFoundError):
        await service.activate_version(template.id, 99)


async def test_get_version_scopes_by_template(service: PromptLibraryService) -> None:
    template_a = await service.create_template(name="a", owner_user_id=uuid4())
    template_b = await service.create_template(name="b", owner_user_id=uuid4())
    await service.create_version(template_a.id, content="a-v1", created_by=uuid4())

    with pytest.raises(PromptVersionNotFoundError):
        await service.get_version(template_b.id, 1)


async def test_list_versions_returns_all_versions_in_order(service: PromptLibraryService) -> None:
    template = await service.create_template(name="t", owner_user_id=uuid4())
    await service.create_version(template.id, content="v1", created_by=uuid4())
    await service.create_version(template.id, content="v2", created_by=uuid4())

    versions = await service.list_versions(template.id)

    assert [v.version_number for v in versions] == [1, 2]


async def test_render_version_substitutes_values(service: PromptLibraryService) -> None:
    template = await service.create_template(name="t", owner_user_id=uuid4())
    await service.create_version(
        template.id,
        content="Hello {{ name }}",
        created_by=uuid4(),
        variables=[PromptVariable(name="name")],
    )

    rendered = await service.render_version(template.id, 1, {"name": "Ada"})

    assert rendered == "Hello Ada"


async def test_render_version_raises_when_required_variable_missing(
    service: PromptLibraryService,
) -> None:
    template = await service.create_template(name="t", owner_user_id=uuid4())
    await service.create_version(
        template.id,
        content="Hello {{ name }}",
        created_by=uuid4(),
        variables=[PromptVariable(name="name", required=True)],
    )

    with pytest.raises(MissingRequiredVariableError):
        await service.render_version(template.id, 1, {})


async def test_list_templates_paginates(service: PromptLibraryService) -> None:
    for i in range(3):
        await service.create_template(name=f"t-{i}", owner_user_id=uuid4())

    page, total = await service.list_templates(limit=2, offset=0)

    assert total == 3
    assert len(page) == 2
