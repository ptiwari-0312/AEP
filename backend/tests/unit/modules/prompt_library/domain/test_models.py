from __future__ import annotations

from uuid import uuid4

from aep.modules.prompt_library.domain.models import (
    PromptTemplate,
    PromptVariable,
    PromptVersion,
)


def test_prompt_variable_defaults_to_required() -> None:
    variable = PromptVariable(name="topic")

    assert variable.required is True


def test_prompt_template_defaults() -> None:
    template = PromptTemplate(id=uuid4(), name="coding-agent-system-prompt", owner_user_id=uuid4())

    assert template.description is None
    assert template.created_at is None


def test_prompt_version_defaults() -> None:
    version = PromptVersion(
        id=uuid4(),
        prompt_template_id=uuid4(),
        version_number=1,
        content="Hello {{ name }}",
        created_by=uuid4(),
    )

    assert version.variables == []
    assert version.is_active is False
