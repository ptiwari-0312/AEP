"""FastAPI routers for the Context Builder (docs/architecture/04-api-design.md §4). Domain
exceptions are translated into `core/errors.py`'s HTTP-mapped `AEPError` subclasses here — the
sole boundary where that translation happens (docs/architecture/09-engineering-standards.md §6);
`domain/` and `services/` know nothing about HTTP.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from aep.core.errors import NotFoundError

from ..domain.errors import (
    ContextPackageNotFoundError,
    FeatureNotFoundError,
    ProjectNotFoundError,
    TaskNotFoundError,
)
from ..domain.models import SourceDocumentType
from ..services.context_builder_service import ContextBuilderService
from .dependencies import get_context_builder_service, get_current_user_id
from .schemas import (
    ContextPackageListResponse,
    ContextPackageResponse,
    ContextPackageSourceListResponse,
    ContextPackageSourceResponse,
    GenerateContextPackageRequest,
    GenerateContextPackageResponse,
    SourceDocumentListResponse,
    SourceDocumentResponse,
)

router = APIRouter(prefix="/api/v1", tags=["context-builder"])


@router.post(
    "/tasks/{task_id}/context-packages",
    response_model=GenerateContextPackageResponse,
    status_code=202,
)
async def generate_context_package(
    task_id: UUID,
    request: GenerateContextPackageRequest,
    service: ContextBuilderService = Depends(get_context_builder_service),
    _user_id: UUID = Depends(get_current_user_id),
) -> GenerateContextPackageResponse:
    # `request.force_reindex` is accepted per the documented contract but is a no-op in this
    # reference implementation: there's no per-project indexed-root configuration yet for a
    # re-index to run against (see this module's README's "Known gaps").
    try:
        package = await service.generate_context_package(task_id, max_tokens=request.max_tokens)
    except TaskNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    except FeatureNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    return GenerateContextPackageResponse(job_id=str(package.id))


@router.get("/tasks/{task_id}/context-packages", response_model=ContextPackageListResponse)
async def list_context_packages(
    task_id: UUID,
    service: ContextBuilderService = Depends(get_context_builder_service),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ContextPackageListResponse:
    try:
        packages, total = await service.list_context_packages_for_task(
            task_id, limit=page_size, offset=(page - 1) * page_size
        )
    except TaskNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    return ContextPackageListResponse(
        items=[ContextPackageResponse.model_validate(p) for p in packages],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/context-packages/{context_package_id}", response_model=ContextPackageResponse)
async def get_context_package(
    context_package_id: UUID,
    service: ContextBuilderService = Depends(get_context_builder_service),
) -> ContextPackageResponse:
    try:
        package = await service.get_context_package(context_package_id)
    except ContextPackageNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    return ContextPackageResponse.model_validate(package)


@router.get(
    "/context-packages/{context_package_id}/sources",
    response_model=ContextPackageSourceListResponse,
)
async def list_context_package_sources(
    context_package_id: UUID,
    service: ContextBuilderService = Depends(get_context_builder_service),
    included: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ContextPackageSourceListResponse:
    try:
        sources, total = await service.list_context_package_sources(
            context_package_id,
            included=included,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
    except ContextPackageNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    return ContextPackageSourceListResponse(
        items=[ContextPackageSourceResponse.model_validate(s) for s in sources],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/projects/{project_id}/source-documents", response_model=SourceDocumentListResponse)
async def list_source_documents(
    project_id: UUID,
    service: ContextBuilderService = Depends(get_context_builder_service),
    doc_type: SourceDocumentType | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> SourceDocumentListResponse:
    try:
        documents, total = await service.list_source_documents_for_project(
            project_id, doc_type=doc_type, limit=page_size, offset=(page - 1) * page_size
        )
    except ProjectNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    return SourceDocumentListResponse(
        items=[SourceDocumentResponse.model_validate(d) for d in documents],
        page=page,
        page_size=page_size,
        total=total,
    )
