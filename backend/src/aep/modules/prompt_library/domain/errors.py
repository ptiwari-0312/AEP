"""Domain-level errors for the Prompt Library — pure Python, no framework imports, and no
dependency on `core/errors.py`'s HTTP-mapped `AEPError` hierarchy either: the `api/` layer is the
sole translation boundary between these and an HTTP response
(docs/architecture/09-engineering-standards.md §6).
"""

from __future__ import annotations

from uuid import UUID


class PromptLibraryDomainError(Exception):
    """Base class for every Prompt Library domain error."""


class PromptTemplateNotFoundError(PromptLibraryDomainError):
    def __init__(self, template_id: UUID) -> None:
        super().__init__(f"prompt template {template_id} not found")
        self.template_id = template_id


class PromptTemplateNameExistsError(PromptLibraryDomainError):
    def __init__(self, name: str) -> None:
        super().__init__(f"a prompt template named {name!r} already exists")
        self.name = name


class PromptVersionNotFoundError(PromptLibraryDomainError):
    def __init__(self, template_id: UUID, version_number: int) -> None:
        super().__init__(f"version {version_number} of prompt template {template_id} not found")
        self.template_id = template_id
        self.version_number = version_number


class UndeclaredVariableReferencedError(PromptLibraryDomainError):
    def __init__(self, undeclared: set[str]) -> None:
        names = ", ".join(sorted(undeclared))
        super().__init__(f"content references undeclared variable(s): {names}")
        self.undeclared = undeclared


class VersionAlreadyActiveError(PromptLibraryDomainError):
    def __init__(self, template_id: UUID, version_number: int) -> None:
        super().__init__(f"version {version_number} of prompt template {template_id} is already active")
        self.template_id = template_id
        self.version_number = version_number


class MissingRequiredVariableError(PromptLibraryDomainError):
    def __init__(self, missing: set[str]) -> None:
        names = ", ".join(sorted(missing))
        super().__init__(f"missing required variable(s): {names}")
        self.missing = missing
