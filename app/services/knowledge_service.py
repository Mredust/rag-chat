"""知识库业务逻辑：知识空间与文档的增删改查。"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import Chunk, Document, DocumentStatus, KnowledgeSpace
from app.schemas.knowledge import (
    DocumentCreate,
    DocumentUpdate,
    KnowledgeSpaceCreate,
    KnowledgeSpaceUpdate,
)

logger = logging.getLogger(__name__)


# ===== 知识空间 =====


async def create_space(db: AsyncSession, user_id: str, data: KnowledgeSpaceCreate) -> KnowledgeSpace:
    space = KnowledgeSpace(user_id=user_id, name=data.name, description=data.description)
    db.add(space)
    await db.commit()
    await db.refresh(space)
    return space


async def list_spaces(db: AsyncSession, user_id: str) -> list[KnowledgeSpace]:
    result = await db.execute(
        select(KnowledgeSpace)
        .where(KnowledgeSpace.user_id == user_id)
        .order_by(KnowledgeSpace.created_at.desc())
    )
    return list(result.scalars().all())


async def get_space(db: AsyncSession, user_id: str, space_id: str) -> KnowledgeSpace | None:
    result = await db.execute(
        select(KnowledgeSpace).where(KnowledgeSpace.id == space_id, KnowledgeSpace.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def update_space(db: AsyncSession, space: KnowledgeSpace, data: KnowledgeSpaceUpdate) -> KnowledgeSpace:
    payload = data.model_dump(exclude_unset=True)
    for key, value in payload.items():
        setattr(space, key, value)
    await db.commit()
    await db.refresh(space)
    return space


async def delete_space(db: AsyncSession, space: KnowledgeSpace) -> None:
    # 同步清理 Chroma 中的空间向量
    from app.services.ingest import remove_space_vectors

    remove_space_vectors(space.id)
    await db.delete(space)
    await db.commit()
    logger.info("知识库删除成功: space_id=%s", space.id)


# ===== 文档 =====


async def create_document(db: AsyncSession, space: KnowledgeSpace, data: DocumentCreate) -> Document:
    doc = Document(
        space_id=space.id,
        filename=data.filename,
        file_type=data.file_type,
        file_size=data.file_size,
        storage_path=data.storage_path,
        status=DocumentStatus.PENDING.value,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return doc


async def list_documents(db: AsyncSession, space_id: str) -> list[Document]:
    result = await db.execute(
        select(Document).where(Document.space_id == space_id).order_by(Document.created_at.desc())
    )
    return list(result.scalars().all())


async def get_document(db: AsyncSession, space_id: str, doc_id: str) -> Document | None:
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.space_id == space_id)
    )
    return result.scalar_one_or_none()


async def update_document(db: AsyncSession, doc: Document, data: DocumentUpdate) -> Document:
    payload = data.model_dump(exclude_unset=True)
    for key, value in payload.items():
        setattr(doc, key, value)
    await db.commit()
    await db.refresh(doc)
    return doc


async def delete_document(db: AsyncSession, doc: Document) -> None:
    # 同步清理 Chroma 中的文档向量
    from app.services.ingest import remove_document_vectors

    remove_document_vectors(doc.id)
    await db.delete(doc)
    await db.commit()
    logger.info("文档删除成功: doc_id=%s", doc.id)


async def list_chunks(db: AsyncSession, doc_id: str) -> list[Chunk]:
    """列出某文档的全部切片（按序号升序）。"""
    result = await db.execute(
        select(Chunk).where(Chunk.document_id == doc_id).order_by(Chunk.chunk_index)
    )
    return list(result.scalars().all())