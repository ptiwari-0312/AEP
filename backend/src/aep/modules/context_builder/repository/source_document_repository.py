"""Data access for `source_documents` (docs/architecture/03-db-design.md §13). The only place in
this module allowed to import SQLAlchemy for this table (docs/architecture/02-repo-design.md §2).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.models import SourceDocument, SourceDocumentType
from .models import SourceDocumentModel


class SourceDocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, document: SourceDocument) -> SourceDocument:
        model = _to_model(document)
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _to_domain(model)

    async def get_by_id(self, source_document_id: UUID) -> SourceDocument | None:
        model = await self._session.get(SourceDocumentModel, source_document_id)
        return _to_domain(model) if model else None

    async def get_many_by_ids(self, source_document_ids: list[UUID]) -> list[SourceDocument]:
        if not source_document_ids:
            return []
        result = await self._session.execute(
            select(SourceDocumentModel).where(SourceDocumentModel.id.in_(source_document_ids))
        )
        return [_to_domain(m) for m in result.scalars().all()]

    async def get_by_project_and_uri(self, project_id: UUID, uri: str) -> SourceDocument | None:
        result = await self._session.execute(
            select(SourceDocumentModel).where(
                SourceDocumentModel.project_id == project_id, SourceDocumentModel.uri == uri
            )
        )
        model = result.scalar_one_or_none()
        return _to_domain(model) if model else None

    async def update(self, document: SourceDocument) -> SourceDocument:
        model = await self._session.get(SourceDocumentModel, document.id)
        if model is None:
            raise ValueError(f"source document {document.id} does not exist — call add() first")
        model.doc_type = document.doc_type.value
        model.content_hash = document.content_hash
        model.last_indexed_at = document.last_indexed_at
        await self._session.flush()
        await self._session.refresh(model)
        return _to_domain(model)

    async def list_for_project(
        self,
        project_id: UUID,
        *,
        doc_type: SourceDocumentType | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[SourceDocument], int]:
        query = select(SourceDocumentModel).where(SourceDocumentModel.project_id == project_id)
        count_query = (
            select(func.count())
            .select_from(SourceDocumentModel)
            .where(SourceDocumentModel.project_id == project_id)
        )
        if doc_type is not None:
            query = query.where(SourceDocumentModel.doc_type == doc_type.value)
            count_query = count_query.where(SourceDocumentModel.doc_type == doc_type.value)

        total = (await self._session.execute(count_query)).scalar_one()

        query = query.order_by(SourceDocumentModel.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(query)
        return [_to_domain(m) for m in result.scalars().all()], total


def _to_domain(model: SourceDocumentModel) -> SourceDocument:
    return SourceDocument(
        id=model.id,
        project_id=model.project_id,
        doc_type=SourceDocumentType(model.doc_type),
        uri=model.uri,
        content_hash=model.content_hash,
        last_indexed_at=model.last_indexed_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _to_model(document: SourceDocument) -> SourceDocumentModel:
    return SourceDocumentModel(
        id=document.id,
        project_id=document.project_id,
        doc_type=document.doc_type.value,
        uri=document.uri,
        content_hash=document.content_hash,
        last_indexed_at=document.last_indexed_at,
    )
