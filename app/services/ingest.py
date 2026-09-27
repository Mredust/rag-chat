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


# ---- 数据库兜底命中后的向量异步回填（读写一致性自愈） ----
# 进程内去重：防止并发请求对同一批 chunk 重复嵌入
_BACKFILL_INFLIGHT: set[str] = set()
# 持有后台任务引用，避免被垃圾回收导致回填中断
_BACKFILL_TASKS: set[asyncio.Task] = set()


def schedule_backfill(chunks: list[dict], cfg: dict) -> None:
    """分层检索第二层（数据库）命中后，异步把缺失向量补齐到向量库，不阻塞本次回答。"""
    if not chunks:
        return
    task = asyncio.create_task(backfill_vectors(chunks, cfg))
    _BACKFILL_TASKS.add(task)
    task.add_done_callback(_BACKFILL_TASKS.discard)


async def backfill_vectors(chunks: list[dict], cfg: dict) -> int:
    """把「MySQL 已有、Chroma 缺失」的切片向量异步补齐，保证读写一致。

    一致性保证：
    - 写前再查一次主库，只回填仍存在的切片（避免与删除文档竞态产生孤儿向量）；
    - 按 chunk_id 幂等 upsert，重复调用/多请求并发安全；
    - 内容取自主库（MySQL 为读写基准），嵌入失败仅告警，由下次回填或启动自检修重试。
    """
    ids = [str(c.get("chunk_id") or "") for c in chunks]
    ids = [i for i in ids if i and i not in _BACKFILL_INFLIGHT]
    if not ids:
        return 0
    _BACKFILL_INFLIGHT.update(ids)
    try:
        async with SessionLocal() as db:
            rows = (
                (await db.execute(select(Chunk).where(Chunk.id.in_(ids)))).scalars().all()
            )
        if not rows:
            return 0  # 切片已被删除，不写入（防孤儿向量）
        collection = get_collection()
        existing = set(
            await asyncio.to_thread(_existing_vector_ids, collection, [c.id for c in rows])
        )
        missing = [c for c in rows if c.id not in existing]
        if not missing:
            return 0
        embedder = build_embedder(cfg)
        vectors = await asyncio.to_thread(embedder.embed, [c.content for c in missing])
        await asyncio.to_thread(
            collection.upsert,
            ids=[c.id for c in missing],
            documents=[c.content for c in missing],
            metadatas=[
                {"space_id": c.space_id, "document_id": c.document_id, "chunk_id": c.id}
                for c in missing
            ],
            embeddings=vectors,
        )
        logger.info("向量库异步回填完成: %d/%d 条", len(missing), len(ids))
        return len(missing)
    except Exception as exc:  # noqa: BLE001 - 回填失败不影响本次回答
        logger.warning("向量库异步回填失败（下次检索或启动自检会重试）: %s", exc)
        return 0
    finally:
        _BACKFILL_INFLIGHT.difference_update(ids)


def _existing_vector_ids(collection, ids: list[str]) -> set[str]:
    """查询给定 chunk_id 中已存在于向量库的 ID 集合。"""
    try:
        return set(collection.get(ids=ids).get("ids") or [])
    except Exception:  # noqa: BLE001 - 查询失败按「全部缺失」处理（upsert 幂等）
        return set()


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
    # 读写一致性：先提交主库（MySQL 切片），再写向量库（Chroma）。
    # 若向量写入中途失败，主库有、向量库缺 → 分层检索第二层数据库兜底可用，
    # 且异步回填/启动自检会补齐向量；避免「向量库有、主库无」的孤儿向量命中脏数据。
    await db.commit()

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

    # 6) 可选：入库成功后清理原始上传文件（切片已入 MySQL、向量已入 Chroma，检索不依赖原文件）
    #    注意：清理后无法重新解析/重新切片该文档，需重新上传；开关 cleanup_upload_files（默认开启）
    if str(cfg.get("cleanup_upload_files", "true")).strip().lower() in ("1", "true", "yes", "on"):
        _cleanup_upload_file(doc.storage_path)


def _cleanup_upload_file(storage_path: str | None) -> None:
    """删除 data/uploads 下的上传原文件（仅限上传目录内），并清理随之变空的目录。"""
    if not storage_path:
        return
    target = to_abs_path(storage_path)
    upload_root = UPLOAD_DIR.resolve()
    try:
        if not target.is_relative_to(upload_root):
            return
        target.unlink(missing_ok=True)
        parent = target.parent
        while parent != upload_root and parent.is_relative_to(upload_root):
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
        logger.info("已清理上传原文件（切片/向量已入库）: %s", storage_path)
    except OSError as exc:  # noqa: BLE001 - 清理失败不影响入库结果
        logger.warning("清理上传原文件失败: %s (%s)", storage_path, exc)


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


async def repair_vectors() -> tuple[int, int]:
    """对齐 MySQL 切片与 Chroma 向量（返回：补齐向量数, 清理孤儿向量数）。

    两边可能因跨机器同步、库恢复、向量目录漂移等原因不一致：
    - MySQL 有切片但 Chroma 缺向量 → 向量检索命中为 0（语义检索失效）；
    - Chroma 有向量但 MySQL 无切片 → 孤儿向量，白白占用存储且可能命中脏数据。
    幂等：仅在有差异时做嵌入/删除，健康状态只做一次 ID 比对（开销很小）。
    """
    collection = get_collection()
    async with SessionLocal() as db:
        chunks = (await db.execute(select(Chunk))).scalars().all()
        cfg = await config_service.get_runtime(db)
    valid: dict[str, Chunk] = {c.id: c for c in chunks}
    existing = set(collection.get()["ids"])

    orphan = sorted(existing - set(valid))
    missing = [cid for cid in valid if cid not in existing]

    if not orphan and not missing:
        return 0, 0

    logger.warning(
        "向量库与切片表不一致: 缺失向量=%d, 孤儿向量=%d，开始对齐",
        len(missing), len(orphan),
    )

    removed = 0
    for i in range(0, len(orphan), 500):
        batch = orphan[i:i + 500]
        await asyncio.to_thread(collection.delete, ids=batch)
        removed += len(batch)

    embedded = 0
    if missing:
        embedder = build_embedder(cfg)
        items = [valid[cid] for cid in missing]
        for i in range(0, len(items), 64):
            batch = items[i:i + 64]
            vectors = await asyncio.to_thread(embedder.embed, [c.content for c in batch])
            await asyncio.to_thread(
                collection.upsert,
                ids=[c.id for c in batch],
                documents=[c.content for c in batch],
                metadatas=[
                    {"space_id": c.space_id, "document_id": c.document_id, "chunk_id": c.id}
                    for c in batch
                ],
                embeddings=vectors,
            )
            embedded += len(batch)
            logger.info("向量补齐进度: %d/%d", embedded, len(missing))
    logger.info("向量库对齐完成: 补齐=%d, 清理孤儿=%d", embedded, removed)
    return embedded, removed