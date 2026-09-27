"""知识库业务逻辑：知识空间与文档的增删改查。"""
from __future__ import annotations

import logging
import shutil

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import Chunk, Document, DocumentStatus, KnowledgeSpace
from app.schemas.knowledge import (
    DocumentCreate,
    DocumentUpdate,
    KnowledgeSpaceCreate,
    KnowledgeSpaceUpdate,
)
from app.services.ingest import UPLOAD_DIR
from app.utils.paths import to_abs_path

logger = logging.getLogger(__name__)


def _remove_uploaded_file(storage_path: str | None) -> None:
    """删除磁盘上的上传文件，仅允许删除 data/uploads 目录内的文件。"""
    if not storage_path:
        return
    target = to_abs_path(storage_path)
    try:
        if not target.is_relative_to(UPLOAD_DIR.resolve()):
            logger.warning("跳过非上传目录内的文件清理: %s", target)
            return
        target.unlink(missing_ok=True)
    except OSError as exc:  # noqa: BLE001 - 清理失败不影响删除主流程
        logger.warning("上传文件清理失败: %s (%s)", target, exc)


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
    # 清理该空间在磁盘上的全部上传文件
    space_dir = UPLOAD_DIR / space.id
    if space_dir.is_dir():
        shutil.rmtree(space_dir, ignore_errors=True)
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
    storage_path = doc.storage_path
    await db.delete(doc)
    await db.commit()
    # 清理磁盘上的上传文件
    _remove_uploaded_file(storage_path)
    logger.info("文档删除成功: doc_id=%s", doc.id)


async def list_chunks(db: AsyncSession, doc_id: str) -> list[Chunk]:
    """列出某文档的全部切片（按序号升序）。"""
    result = await db.execute(
        select(Chunk).where(Chunk.document_id == doc_id).order_by(Chunk.chunk_index)
    )
    return list(result.scalars().all())