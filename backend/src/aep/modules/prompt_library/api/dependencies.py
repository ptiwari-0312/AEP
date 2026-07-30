"""FastAPI dependency providers for the Prompt Library."""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from aep.core.db import get_db_session
from aep.core.security import get_current_user_id

from ..repository.prompt_template_repository import PromptTemplateRepository
from ..repository.prompt_version_repository import PromptVersionRepository
from ..services.prompt_library_service import PromptLibraryService

__all__ = ["get_current_user_id", "get_prompt_library_service"]


def get_prompt_library_service(
    session: AsyncSession = Depends(get_db_session),
) -> PromptLibraryService:
    return PromptLibraryService(PromptTemplateRepository(session), PromptVersionRepository(session))
