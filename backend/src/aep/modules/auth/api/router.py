"""FastAPI routers for the Authentication Service (docs/architecture/04-api-design.md §1, §10).
Domain exceptions are translated into `core/errors.py`'s HTTP-mapped `AEPError` subclasses here
(docs/architecture/09-engineering-standards.md §6).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from aep.core.errors import (
    ConflictError,
    NotFoundError,
    UnauthorizedError,
    ValidationFailedError,
)
from aep.core.security import AuthenticatedUser, get_current_user, require_role

from ..domain.errors import (
    InvalidRefreshTokenError,
    OAuthExchangeError,
    RoleAlreadyGrantedError,
    RoleNotFoundError,
    RoleNotGrantedError,
    UnsupportedOAuthProviderError,
    UserNotFoundError,
)
from ..domain.models import UserStatus
from ..services.audit_service import AuditService
from ..services.auth_service import AuthService
from ..services.user_service import UserService
from .dependencies import get_audit_service, get_auth_service, get_user_service
from .schemas import (
    AuditEventListResponse,
    AuditEventResponse,
    CurrentUserResponse,
    GrantRoleRequest,
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    RefreshRequest,
    RefreshResponse,
    RoleResponse,
    UserListResponse,
    UserRoleResponse,
    UserSummary,
    UserUpdateRequest,
)

router = APIRouter(prefix="/api/v1", tags=["auth"])


# ---- Auth ----------------------------------------------------------------------------------


@router.post("/auth/login", response_model=LoginResponse)
async def login(
    request: LoginRequest, service: AuthService = Depends(get_auth_service)
) -> LoginResponse:
    try:
        result = await service.login(provider=request.provider, code=request.code)
    except UnsupportedOAuthProviderError as exc:
        raise ValidationFailedError(
            str(exc), errors=[{"field": "provider", "message": "must be a configured provider"}]
        ) from exc
    except OAuthExchangeError as exc:
        raise UnauthorizedError(str(exc)) from exc
    return LoginResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_in=result.expires_in,
        user=UserSummary.model_validate(result.user),
    )


@router.post("/auth/refresh", response_model=RefreshResponse)
async def refresh(
    request: RefreshRequest, service: AuthService = Depends(get_auth_service)
) -> RefreshResponse:
    try:
        result = await service.refresh(refresh_token=request.refresh_token)
    except InvalidRefreshTokenError as exc:
        raise UnauthorizedError(str(exc)) from exc
    return RefreshResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_in=result.expires_in,
    )


@router.post("/auth/logout", status_code=204)
async def logout(
    request: LogoutRequest,
    service: AuthService = Depends(get_auth_service),
    _user: AuthenticatedUser = Depends(get_current_user),
) -> None:
    await service.logout(refresh_token=request.refresh_token)


# ---- Users ----------------------------------------------------------------------------------


@router.get("/users/me", response_model=CurrentUserResponse)
async def get_me(
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
) -> CurrentUserResponse:
    user = await service.get_user(current_user.user_id)
    return CurrentUserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        status=user.status,
        roles=user.roles,
        created_at=user.created_at,
    )


@router.get("/users", response_model=UserListResponse, dependencies=[Depends(require_role("admin"))])
async def list_users(
    service: UserService = Depends(get_user_service),
    status_filter: UserStatus | None = Query(default=None, alias="status"),
    email: str | None = Query(default=None),
    sort: str = Query(default="-created_at"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> UserListResponse:
    users, total = await service.list_users(
        status=status_filter, email=email, sort=sort, limit=page_size, offset=(page - 1) * page_size
    )
    return UserListResponse(
        items=[UserSummary.model_validate(u) for u in users], page=page, page_size=page_size, total=total
    )


@router.get(
    "/users/{user_id}", response_model=UserSummary, dependencies=[Depends(require_role("admin"))]
)
async def get_user(user_id: UUID, service: UserService = Depends(get_user_service)) -> UserSummary:
    try:
        user = await service.get_user(user_id)
    except UserNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    return UserSummary.model_validate(user)


@router.patch(
    "/users/{user_id}", response_model=UserSummary, dependencies=[Depends(require_role("admin"))]
)
async def update_user(
    user_id: UUID, request: UserUpdateRequest, service: UserService = Depends(get_user_service)
) -> UserSummary:
    try:
        user = await service.update_user(user_id, display_name=request.display_name, status=request.status)
    except UserNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    return UserSummary.model_validate(user)


# ---- Roles ------------------------------------------------------------------------------------


@router.get("/roles", response_model=list[RoleResponse])
async def list_roles(
    service: UserService = Depends(get_user_service),
    _user: AuthenticatedUser = Depends(get_current_user),
) -> list[RoleResponse]:
    roles = await service.list_roles()
    return [RoleResponse.model_validate(r) for r in roles]


@router.post(
    "/users/{user_id}/roles",
    response_model=UserRoleResponse,
    status_code=201,
    dependencies=[Depends(require_role("admin"))],
)
async def grant_role(
    user_id: UUID,
    request: GrantRoleRequest,
    service: UserService = Depends(get_user_service),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> UserRoleResponse:
    try:
        user_role = await service.grant_role(
            user_id, role_id=request.role_id, granted_by=current_user.user_id
        )
    except (UserNotFoundError, RoleNotFoundError) as exc:
        raise NotFoundError(str(exc)) from exc
    except RoleAlreadyGrantedError as exc:
        raise ConflictError(str(exc)) from exc
    return UserRoleResponse(
        user_id=user_role.user_id,
        role_id=user_role.role_id,
        granted_at=user_role.granted_at,
        granted_by=user_role.granted_by,
    )


@router.delete(
    "/users/{user_id}/roles/{role_id}",
    status_code=204,
    dependencies=[Depends(require_role("admin"))],
)
async def revoke_role(
    user_id: UUID, role_id: UUID, service: UserService = Depends(get_user_service)
) -> None:
    try:
        await service.revoke_role(user_id, role_id)
    except (UserNotFoundError, RoleNotFoundError, RoleNotGrantedError) as exc:
        raise NotFoundError(str(exc)) from exc


# ---- Audit --------------------------------------------------------------------------------


@router.get(
    "/audit-events",
    response_model=AuditEventListResponse,
    dependencies=[Depends(require_role("admin"))],
)
async def list_audit_events(
    service: AuditService = Depends(get_audit_service),
    entity_type: str | None = Query(default=None),
    entity_id: UUID | None = Query(default=None),
    event_type: str | None = Query(default=None),
    actor_user_id: UUID | None = Query(default=None),
    actor_agent_id: UUID | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
) -> AuditEventListResponse:
    events, next_cursor, has_more = await service.list_events(
        entity_type=entity_type,
        entity_id=entity_id,
        event_type=event_type,
        actor_user_id=actor_user_id,
        actor_agent_id=actor_agent_id,
        cursor=cursor,
        limit=limit,
    )
    items = [AuditEventResponse.model_validate(e) for e in events]
    return AuditEventListResponse(items=items, next_cursor=next_cursor, has_more=has_more)


@router.get(
    "/audit-events/{event_id}",
    response_model=AuditEventResponse,
    dependencies=[Depends(require_role("admin"))],
)
async def get_audit_event(
    event_id: UUID, service: AuditService = Depends(get_audit_service)
) -> AuditEventResponse:
    event = await service.get_event(event_id)
    if event is None:
        raise NotFoundError(f"audit event {event_id} not found")
    return AuditEventResponse.model_validate(event)
