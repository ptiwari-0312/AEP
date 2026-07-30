"""FastAPI routers for the Prompt Library (docs/architecture/04-api-design.md §6). Domain
exceptions are translated into `core/errors.py`'s HTTP-mapped `AEPError` subclasses here — the
sole boundary where that translation happens (docs/architecture/09-engineering-standards.md §6);
`domain/` and `services/` know nothing about HTTP.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from aep.core.errors import ConflictError, NotFoundError, ValidationFailedError

from ..domain.errors import (
    PromptTemplateNameExistsError,
    PromptTemplateNotFoundError,
    PromptVersionNotFoundError,
    UndeclaredVariableReferencedError,
    VersionAlreadyActiveError,
)
from ..domain.models import PromptVariable
from ..services.prompt_library_service import PromptLibraryService
from .dependencies import get_current_user_id, get_prompt_library_service
from .schemas import (
    PromptTemplateCreateRequest,
    PromptTemplateListResponse,
    PromptTemplateResponse,
    PromptVersionCreateRequest,
    PromptVersionResponse,
)

router = APIRouter(prefix="/api/v1", tags=["prompt-library"])


# ---- Templates --------------------------------------------------------------------------


@router.post("/prompt-templates", response_model=PromptTemplateResponse, status_code=201)
async def create_template(
    request: PromptTemplateCreateRequest,
    service: PromptLibraryService = Depends(get_prompt_library_service),
    owner_user_id: UUID = Depends(get_current_user_id),
) -> PromptTemplateResponse:
    try:
        template = await service.create_template(
            name=request.name, owner_user_id=owner_user_id, description=request.description
        )
    except PromptTemplateNameExistsError as exc:
        raise ConflictError(str(exc)) from exc
    return PromptTemplateResponse.model_validate(template)


@router.get("/prompt-templates", response_model=PromptTemplateListResponse)
async def list_templates(
    service: PromptLibraryService = Depends(get_prompt_library_service),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PromptTemplateListResponse:
    templates, total = await service.list_templates(limit=page_size, offset=(page - 1) * page_size)
    return PromptTemplateListResponse(
        items=[PromptTemplateResponse.model_validate(t) for t in templates],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/prompt-templates/{template_id}", response_model=PromptTemplateResponse)
async def get_template(
    template_id: UUID, service: PromptLibraryService = Depends(get_prompt_library_service)
) -> PromptTemplateResponse:
    try:
        template, active_version = await service.get_template_with_active_version(template_id)
    except PromptTemplateNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    response = PromptTemplateResponse.model_validate(template)
    if active_version is not None:
        response = response.model_copy(
            update={"active_version": PromptVersionResponse.model_validate(active_version)}
        )
    return response


# ---- Versions ----------------------------------------------------------------------------


@router.post(
    "/prompt-templates/{template_id}/versions",
    response_model=PromptVersionResponse,
    status_code=201,
)
async def create_version(
    template_id: UUID,
    request: PromptVersionCreateRequest,
    service: PromptLibraryService = Depends(get_prompt_library_service),
    created_by: UUID = Depends(get_current_user_id),
) -> PromptVersionResponse:
    try:
        version = await service.create_version(
            template_id,
            content=request.content,
            created_by=created_by,
            variables=[PromptVariable(name=v.name, required=v.required) for v in request.variables],
            activate=request.activate,
        )
    except PromptTemplateNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    except UndeclaredVariableReferencedError as exc:
        raise ValidationFailedError(
            str(exc), errors=[{"field": "content", "message": str(exc)}]
        ) from exc
    return PromptVersionResponse.model_validate(version)


@router.get(
    "/prompt-templates/{template_id}/versions", response_model=list[PromptVersionResponse]
)
async def list_versions(
    template_id: UUID, service: PromptLibraryService = Depends(get_prompt_library_service)
) -> list[PromptVersionResponse]:
    try:
        versions = await service.list_versions(template_id)
    except PromptTemplateNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    return [PromptVersionResponse.model_validate(v) for v in versions]


@router.get(
    "/prompt-templates/{template_id}/versions/{version_number}",
    response_model=PromptVersionResponse,
)
async def get_version(
    template_id: UUID,
    version_number: int,
    service: PromptLibraryService = Depends(get_prompt_library_service),
) -> PromptVersionResponse:
    try:
        version = await service.get_version(template_id, version_number)
    except (PromptTemplateNotFoundError, PromptVersionNotFoundError) as exc:
        raise NotFoundError(str(exc)) from exc
    return PromptVersionResponse.model_validate(version)


@router.post(
    "/prompt-templates/{template_id}/versions/{version_number}/activate",
    response_model=PromptVersionResponse,
)
async def activate_version(
    template_id: UUID,
    version_number: int,
    service: PromptLibraryService = Depends(get_prompt_library_service),
) -> PromptVersionResponse:
    try:
        version = await service.activate_version(template_id, version_number)
    except (PromptTemplateNotFoundError, PromptVersionNotFoundError) as exc:
        raise NotFoundError(str(exc)) from exc
    except VersionAlreadyActiveError as exc:
        raise ConflictError(str(exc)) from exc
    return PromptVersionResponse.model_validate(version)
