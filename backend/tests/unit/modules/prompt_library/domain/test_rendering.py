from __future__ import annotations

import pytest

from aep.modules.prompt_library.domain.errors import (
    MissingRequiredVariableError,
    UndeclaredVariableReferencedError,
)
from aep.modules.prompt_library.domain.models import PromptVariable
from aep.modules.prompt_library.domain.rendering import (
    extract_referenced_variables,
    render,
    validate_variables_declared,
)


def test_extract_referenced_variables_finds_all_placeholders() -> None:
    content = "Hello {{ name }}, your topic is {{topic}}."

    assert extract_referenced_variables(content) == {"name", "topic"}


def test_extract_referenced_variables_empty_when_none_present() -> None:
    assert extract_referenced_variables("no placeholders here") == set()


def test_validate_variables_declared_passes_when_all_referenced_are_declared() -> None:
    validate_variables_declared(
        "Hello {{ name }}", [PromptVariable(name="name"), PromptVariable(name="unused")]
    )  # no raise


def test_validate_variables_declared_raises_for_undeclared_reference() -> None:
    with pytest.raises(UndeclaredVariableReferencedError) as exc_info:
        validate_variables_declared("Hello {{ name }}", [])

    assert exc_info.value.undeclared == {"name"}


def test_render_substitutes_provided_values() -> None:
    result = render("Hello {{ name }}!", [PromptVariable(name="name")], {"name": "Ada"})

    assert result == "Hello Ada!"


def test_render_raises_when_required_variable_missing() -> None:
    with pytest.raises(MissingRequiredVariableError) as exc_info:
        render("Hello {{ name }}!", [PromptVariable(name="name", required=True)], {})

    assert exc_info.value.missing == {"name"}


def test_render_leaves_unprovided_optional_variable_as_literal_placeholder() -> None:
    result = render(
        "Hi {{ name }}, aka {{ nickname }}",
        [PromptVariable(name="name"), PromptVariable(name="nickname", required=False)],
        {"name": "Ada"},
    )

    assert result == "Hi Ada, aka {{ nickname }}"
