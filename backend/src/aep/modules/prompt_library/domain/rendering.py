"""Variable extraction and rendering — pure functions, no framework/DB imports
(docs/architecture/09-engineering-standards.md §9: "a prompt referencing a variable not
declared, or a caller omitting a required one, fails at activation/render time, not silently at
generation time with a malformed prompt").

Placeholder syntax is `{{ name }}` (Jinja2-style double braces, no Jinja2 dependency — this is a
simple regex substitution, not a template engine) since neither the API design doc nor the
engineering standards doc specifies one; this is a reference implementation's own concrete choice
for an otherwise-unspecified detail, not a re-derivation of a documented requirement.
"""

from __future__ import annotations

import re
from typing import Any

from .errors import MissingRequiredVariableError, UndeclaredVariableReferencedError
from .models import PromptVariable

_VARIABLE_PATTERN = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def extract_referenced_variables(content: str) -> set[str]:
    return set(_VARIABLE_PATTERN.findall(content))


def validate_variables_declared(content: str, variables: list[PromptVariable]) -> None:
    """Raises if `content` references a placeholder not present in `variables` — the 422
    condition docs/architecture/04-api-design.md §6 specifies for `POST .../versions`."""
    referenced = extract_referenced_variables(content)
    declared = {variable.name for variable in variables}
    undeclared = referenced - declared
    if undeclared:
        raise UndeclaredVariableReferencedError(undeclared)


def render(content: str, variables: list[PromptVariable], values: dict[str, Any]) -> str:
    """Substitutes `{{ name }}` placeholders with `values`. Raises if a `required` variable has
    no supplied value — the "render time" failure docs/architecture/09-engineering-standards.md
    §9 calls for. An *optional* variable with no supplied value is left as its literal
    `{{name}}` placeholder in the output — an explicit signal that it wasn't provided, rather
    than being silently blanked to an empty string.
    """
    required_names = {variable.name for variable in variables if variable.required}
    missing = required_names - values.keys()
    if missing:
        raise MissingRequiredVariableError(missing)

    def _substitute(match: re.Match[str]) -> str:
        name = match.group(1)
        return str(values[name]) if name in values else match.group(0)

    return _VARIABLE_PATTERN.sub(_substitute, content)
