"""文档入库管线：上传落盘、解析、切片、向量化、写入 Chroma 与 MySQL。

流程：parse_text（解析）→ split_text（切片）→ embed（向量化）→
Chunk 写入 MySQL、向量写入 Chroma → 更新 Document 状态/统计。
由 upload 接口触发後在后台任务中执行。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import build_embedder
from app.core.config import BASE_DIR, settings
from app.db.database import SessionLocal
from app.models.knowledge import Chunk, Document, DocumentStatus
from app.rag.chroma_store import get_collection
from app.services import config_service
from app.services.parsing import (
    clean_text,
    parse_text,
    split_hierarchical,
    split_text,
)
from app.utils.paths import to_abs_path, to_rel_path

logger = logging.getLogger(__name__)

UPLOAD_DIR: Path = BASE_DIR / "data" / "uploads"

# 文档入库策略（doc_id -> 用户在导入向导中选择的解析/分段配置）
# 仅用于异步入库线程读取，不入库持久化。
_INGEST_STRATEGIES: dict[str, dict] = {}


def save_upload(space_id: str, doc_id: str, filename: str, content: bytes) -> str:
    """将上传文件落盘，返回项目根目录下的相对存储路径。"""
    directory = UPLOAD_DIR / space_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{doc_id}_{filename}"
    path.write_bytes(content)
    return to_rel_path(path)


def schedule_ingest(doc_id: str, strategy_config: dict | None = None) -> None:
    """后台任务：处理指定文档（解析→切片→向量化→入库）。"""
    if strategy_config:
        _INGEST_STRATEGIES[doc_id] = strategy_config
    asyncio.create_task(process_document(doc_id))


# 中断后可恢复的文档状态（进程异常退出会导致后台协程终止，文档停留在这些中间态）
_RESUMABLE_STATUSES = {
    DocumentStatus.PENDING.value,
    DocumentStatus.PARSING.value,
    DocumentStatus.CHUNKING.value,
    DocumentStatus.EMBEDDING.value,
}


async def recover_stale_documents() -> int:
    """服务重启后恢复中断的文档入库任务，解决「中途断开后无法继续、前端一直刷新」。

    进程退出会丢失 asyncio.create_task 产生的后台协程，使文档卡在 PENDING/解析中/切片中/
    向量化中状态。这里重新调度这些文档（仅限已落盘的文档），重新执行解析→切片→向量化管线。
    """
    async with SessionLocal() as db:
        result = await db.execute(
            select(Document).where(
                Document.status.in_(_RESUMABLE_STATUSES), Document.storage_path != ""
            )
        )
        docs = [d for d in result.scalars().all() if d.storage_path]
    for doc in docs:
        schedule_ingest(doc.id)
    if docs:
        logger.info("恢复中断的文档入库任务: %d 个", len(docs))
    return len(docs)


async def process_document(doc_id: str) -> None:
    """独立会话中执行入库管线，异常时标记 FAILED。"""
    logger.info("文档入库任务开始: doc_id=%s", doc_id)
    async with SessionLocal() as db:
        result = await db.execute(select(Document).where(Document.id == doc_id))
        doc = result.scalar_one_or_none()
        if not doc:
            logger.warning("入库任务：文档不存在 doc_id=%s", doc_id)
            return
        try:
            await _process(db, doc)
            logger.info("文档入库完成: doc_id=%s, chunks=%d", doc.id, doc.chunk_count)
        except Exception as exc:  # noqa: BLE001 - 记录失败原因
            doc.status = DocumentStatus.FAILED.value
            doc.error_msg = str(exc)[:2000]
            await db.commit()
            logger.exception("文档入库失败: doc_id=%s, error=%s", doc_id, exc)


def chunk_by_strategy(text: str, config: dict) -> list[dict]:
    """按用户在导入向导中选择的策略将文本切分为片段。

    返回 [{content, level, title}]，其中 level/title 仅按层级分段时存在。
    """
    mode = str(config.get("segment_mode") or "auto")
    collapse = bool(config.get("collapse_whitespace", mode == "auto"))
    remove_links = bool(config.get("remove_urls_email", False))
    text = clean_text(text, collapse_whitespace=collapse, remove_urls_email=remove_links)

    if mode == "hierarchy":
        max_level = int(config.get("max_level") or 3)
        keep_hierarchy = bool(config.get("keep_hierarchy", True))
        result: list[dict] = []
        for node in split_hierarchical(text, max_level):
            title = node.get("title") or ""
            body = node.get("content") or ""
            level = int(node.get("level") or 1)
            content = f"{'#' * level} {title}\n{body}".strip() if (title and keep_hierarchy) else (body or title)
            result.append({"content": content, "level": level, "title": title})
        return result

    if mode == "custom":
        chunk_size = int(config.get("chunk_size") or 800)
        overlap_pct = int(config.get("chunk_overlap") or 10)
        separator = str(config.get("separator") or "\n")
        pieces = split_text(
            text,
            chunk_size,
            overlap_pct,
            separators=[separator, "。", "！", "？", "；", ".", "!", "?", ";", " ", ""],
            overlap_mode="ratio",
        )
    else:
        chunk_size = int(config.get("chunk_size") or 512)
        overlap = int(config.get("chunk_overlap") or 50)
        pieces = split_text(text, chunk_size, overlap)

    return [{"content": p, "level": None, "title": None} for p in pieces]


async def _process(db: AsyncSession, doc: Document) -> None:
    # 幂等清理：此前中断可能残留的历史切片与 Chroma 向量，删除避免重复入库
    await db.execute(delete(Chunk).where(Chunk.document_id == doc.id))
    await db.commit()
    remove_document_vectors(doc.id)

    # 1) 解析
    doc.status = DocumentStatus.PARSING.value
    await db.commit()
    text = await asyncio.to_thread(parse_text, doc.file_type, str(to_abs_path(doc.storage_path)))
    logger.debug("文档解析完成: doc_id=%s, type=%s, 字符数=%d", doc.id, doc.file_type, len(text))

    # 2) 切片（优先使用导入向导策略，否则回退切片策略/运行时默认）
    doc.status = DocumentStatus.CHUNKING.value
    await db.commit()
    cfg = await config_service.get_runtime(db)
    strategy_config = _INGEST_STRATEGIES.pop(doc.id, None)
    if strategy_config:
        chunk_items = chunk_by_strategy(text, strategy_config)
        chunk_size = int(strategy_config.get("chunk_size") or doc.chunk_size or 512)
        chunk_overlap = int(strategy_config.get("chunk_overlap") or doc.chunk_overlap or 50)
    else:
        chunk_size = int(config_service.get_int(cfg, "chunk_size", doc.chunk_size or 512))
        chunk_overlap = int(config_service.get_int(cfg, "chunk_overlap", doc.chunk_overlap or 50))
        pieces = split_text(text, chunk_size, chunk_overlap)
        chunk_items = [{"content": p, "level": None, "title": None} for p in pieces]
    if not chunk_items:
        raise ValueError("文档内容为空或无法解析出文本")
    pieces = [c["content"] for c in chunk_items]
    logger.info(
        "文档切片结果: doc_id=%s, chunk_size=%d, overlap=%d, pieces=%d",
        doc.id,
        chunk_size,
        chunk_overlap,
        len(pieces),
    )

    # 3) 向量化 + 落库
    doc.status = DocumentStatus.EMBEDDING.value
    await db.commit()
    embedder = build_embedder(cfg)
    model_name = str(cfg.get("embedding_model", "")).strip()
    vectors = await asyncio.to_thread(embedder.embed, pieces)
    logger.debug("切片向量化完成: doc_id=%s, 向量数=%d", doc.id, len(vectors))

    chunk_rows = [
        Chunk(
            document_id=doc.id,
            space_id=doc.space_id,
            chunk_index=i,
            content=item["content"],
            char_count=len(item["content"]),
            meta={"chunk_index": i, "level": item.get("level"), "title": item.get("title")},
            embedding_model=model_name,
        )
        for i, item in enumerate(chunk_items)
    ]
    db.add_all(chunk_rows)
    await db.flush()  # 先生成 chunk.id

    # 4) 向量写入 Chroma
    collection = get_collection()
    await asyncio.to_thread(
        collection.upsert,
        ids=[c.id for c in chunk_rows],
        documents=[c.content for c in chunk_rows],
        metadatas=[
            {"space_id": doc.space_id, "document_id": doc.id, "chunk_id": c.id}
            for c in chunk_rows
        ],
        embeddings=vectors,
    )
    logger.info("向量写入成功: doc_id=%s, chunks=%d", doc.id, len(chunk_rows))

    # 5) 更新文档统计与状态
    doc.chunk_count = len(chunk_rows)
    doc.char_count = sum(len(p) for p in pieces)
    doc.chunk_size = chunk_size
    doc.chunk_overlap = chunk_overlap
    doc.embedding_model = model_name
    doc.status = DocumentStatus.COMPLETED.value
    doc.processed_at = datetime.now()
    await db.commit()


def remove_document_vectors(document_id: str) -> None:
    """删除某文档在 Chroma 中的全部向量。"""
    collection = get_collection()
    try:
        collection.delete(where={"document_id": document_id})
    except Exception:  # noqa: BLE001 - 集合为空/无可删项时忽略
        pass


def remove_space_vectors(space_id: str) -> None:
    """删除某知识空间在 Chroma 中的全部向量。"""
    collection = get_collection()
    try:
        collection.delete(where={"space_id": space_id})
    except Exception:  # noqa: BLE001
        pass