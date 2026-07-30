"""Prompt Library domain layer — entities, value objects, rendering, and domain exceptions.
Zero framework imports (docs/architecture/02-repo-design.md §2)."""

from .errors import (
    MissingRequiredVariableError,
    PromptLibraryDomainError,
    PromptTemplateNameExistsError,
    PromptTemplateNotFoundError,
    PromptVersionNotFoundError,
    UndeclaredVariableReferencedError,
    VersionAlreadyActiveError,
)
from .models import PromptTemplate, PromptVariable, PromptVersion
from .rendering import extract_referenced_variables, render, validate_variables_declared

__all__ = [
    "MissingRequiredVariableError",
    "PromptLibraryDomainError",
    "PromptTemplate",
    "PromptTemplateNameExistsError",
    "PromptTemplateNotFoundError",
    "PromptVariable",
    "PromptVersion",
    "PromptVersionNotFoundError",
    "UndeclaredVariableReferencedError",
    "VersionAlreadyActiveError",
    "extract_referenced_variables",
    "render",
    "validate_variables_declared",
]
