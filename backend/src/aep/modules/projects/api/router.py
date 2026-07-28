"""FastAPI routers for the Project Service (docs/architecture/04-api-design.md §2). Domain
exceptions are translated into `core/errors.py`'s HTTP-mapped `AEPError` subclasses here —
the sole boundary where that translation happens (docs/architecture/09-engineering-standards.md
§6); `domain/` and `services/` know nothing about HTTP.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query

from aep.core.errors import ConflictError, NotFoundError

from ..domain.errors import (
    FeatureNotFoundError,
    IllegalFeatureStatusTransitionError,
    ProjectAlreadyArchivedError,
    ProjectNotFoundError,
    SlugAlreadyExistsError,
)
from ..domain.models import FeatureStatus, GitRepository, ProjectStatus
from ..repository.git_repository_repository import GitRepositoryRepository
from ..services.feature_service import FeatureService
from ..services.project_service import ProjectService
from .dependencies import (
    get_current_user_id,
    get_feature_service,
    get_git_repository_repository,
    get_project_service,
)
from .schemas import (
    AttachRepositoryRequest,
    FeatureCreateRequest,
    FeatureResponse,
    FeatureStatusTransitionRequest,
    FeatureUpdateRequest,
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdateRequest,
)

router = APIRouter(prefix="/api/v1", tags=["projects"])


# ---- Projects ----------------------------------------------------------------------------


@router.post("/projects", response_model=ProjectResponse, status_code=201)
async def create_project(
    request: ProjectCreateRequest,
    service: ProjectService = Depends(get_project_service),
    owner_user_id: UUID = Depends(get_current_user_id),
) -> ProjectResponse:
    try:
        project = await service.create_project(
            name=request.name,
            slug=request.slug,
            owner_user_id=owner_user_id,
            description=request.description,
            git_repository_id=request.git_repository_id,
        )
    except SlugAlreadyExistsError as exc:
        raise ConflictError(str(exc)) from exc
    return ProjectResponse.model_validate(project)


@router.get("/projects", response_model=ProjectListResponse)
async def list_projects(
    service: ProjectService = Depends(get_project_service),
    status_filter: ProjectStatus | None = Query(default=None, alias="status"),
    owner_user_id: UUID | None = Query(default=None),
    q: str | None = Query(default=None),
    sort: str = Query(default="-created_at"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ProjectListResponse:
    projects, total = await service.list_projects(
        status=status_filter,
        owner_user_id=owner_user_id,
        name_contains=q,
        sort=sort,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return ProjectListResponse(
        items=[ProjectResponse.model_validate(p) for p in projects],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: UUID, service: ProjectService = Depends(get_project_service)
) -> ProjectResponse:
    try:
        project = await service.get_project(project_id)
    except ProjectNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    return ProjectResponse.model_validate(project)


@router.patch("/projects/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: UUID,
    request: ProjectUpdateRequest,
    service: ProjectService = Depends(get_project_service),
) -> ProjectResponse:
    try:
        project = await service.update_project(
            project_id, name=request.name, description=request.description
        )
    except ProjectNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    return ProjectResponse.model_validate(project)


@router.post("/projects/{project_id}/archive", response_model=ProjectResponse)
async def archive_project(
    project_id: UUID, service: ProjectService = Depends(get_project_service)
) -> ProjectResponse:
    try:
        project = await service.archive_project(project_id)
    except ProjectNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    except ProjectAlreadyArchivedError as exc:
        raise ConflictError(str(exc)) from exc
    return ProjectResponse.model_validate(project)


@router.put("/projects/{project_id}/repository", response_model=ProjectResponse)
async def attach_repository(
    project_id: UUID,
    request: AttachRepositoryRequest,
    service: ProjectService = Depends(get_project_service),
    git_repositories: GitRepositoryRepository = Depends(get_git_repository_repository),
) -> ProjectResponse:
    repository = await git_repositories.get_by_url(request.url)
    if repository is None:
        repository = await git_repositories.add(
            GitRepository(
                id=uuid4(),
                name=request.name,
                url=request.url,
                provider=request.provider,
                default_branch=request.default_branch,
            )
        )
    try:
        project = await service.attach_repository(project_id, git_repository_id=repository.id)
    except ProjectNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    return ProjectResponse.model_validate(project)


# ---- Features ----------------------------------------------------------------------------


@router.post("/projects/{project_id}/features", response_model=FeatureResponse, status_code=201)
async def create_feature(
    project_id: UUID,
    request: FeatureCreateRequest,
    service: FeatureService = Depends(get_feature_service),
    created_by: UUID = Depends(get_current_user_id),
) -> FeatureResponse:
    try:
        feature = await service.create_feature(
            project_id=project_id,
            title=request.title,
            created_by=created_by,
            description=request.description,
        )
    except ProjectNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    return FeatureResponse.model_validate(feature)


@router.get("/projects/{project_id}/features", response_model=list[FeatureResponse])
async def list_features(
    project_id: UUID,
    service: FeatureService = Depends(get_feature_service),
    status_filter: FeatureStatus | None = Query(default=None, alias="status"),
) -> list[FeatureResponse]:
    try:
        features = await service.list_features_for_project(project_id, status=status_filter)
    except ProjectNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    return [FeatureResponse.model_validate(f) for f in features]


@router.get("/features/{feature_id}", response_model=FeatureResponse)
async def get_feature(
    feature_id: UUID, service: FeatureService = Depends(get_feature_service)
) -> FeatureResponse:
    try:
        feature = await service.get_feature(feature_id)
    except FeatureNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    return FeatureResponse.model_validate(feature)


@router.patch("/features/{feature_id}", response_model=FeatureResponse)
async def update_feature(
    feature_id: UUID,
    request: FeatureUpdateRequest,
    service: FeatureService = Depends(get_feature_service),
) -> FeatureResponse:
    try:
        feature = await service.update_feature(
            feature_id, title=request.title, description=request.description
        )
    except FeatureNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    return FeatureResponse.model_validate(feature)


@router.post("/features/{feature_id}/status", response_model=FeatureResponse)
async def transition_feature_status(
    feature_id: UUID,
    request: FeatureStatusTransitionRequest,
    service: FeatureService = Depends(get_feature_service),
) -> FeatureResponse:
    try:
        feature = await service.transition_status(feature_id, to_status=request.to_status)
    except FeatureNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    except IllegalFeatureStatusTransitionError as exc:
        raise ConflictError(str(exc)) from exc
    return FeatureResponse.model_validate(feature)
