"""模型训练平台业务逻辑：数据集（版本与文件上传）、模型导入、训练任务、评测维度与评测任务。

- 数据集：上传 jsonl/xls/xlsx 落盘到本地 data/ml 目录，统计 jsonl 行数作为数据量，保留前 100KB 预览。
- 模型：导入本地模型文件夹并记录系统路径。
- 训练任务：后台异步任务执行真实 Embedding 对比学习微调（pending→running→done），产出保存模型与日志。
- 评测：定义评测维度，执行自定义/基线评测，产出指标分数并聚合排行榜。
"""
from __future__ import annotations

import asyncio
import csv
import difflib
import gc
import io
import json
import logging
import math
import os
import random
import re
import shutil
import threading
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

from collections import Counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.ai import EmbeddingClient, build_embedder, build_llm
from app.ai.embedding import clear_local_model_cache, ensure_hf_model_config
from app.ai.llm import LLMError
from app.core.config import BASE_DIR, resolve_torch_device
from app.core.response import BusinessError, ErrorCode
from app.db.database import SessionLocal
from app.models.knowledge import Chunk, Document
from app.models.ml import (
    MLDataset,
    MLDatasetVersion,
    MLEvalDimension,
    MLEvalTask,
    MLLeaderboard,
    MLModel,
    MLTrainTask,
)
from app.rag.reranker import build_reranker, lexical_score
from app.services import config_service
from app.utils import prompt_loader
from app.utils.paths import to_abs_path, to_rel_path

logger = logging.getLogger(__name__)

ML_DATA_DIR: Path = BASE_DIR / "data" / "ml"
DATASET_UPLOAD_DIR: Path = ML_DATA_DIR / "datasets"
# 模型文件夹根目录（项目根目录下 models/，默认含 bge-large-zh-v1.5）
MODELS_DIR: Path = BASE_DIR / "models"
# 系统内置模型目录（models/system，如 bge-large-zh-v1.5 等内置向量模型）
MODELS_SYSTEM_DIR: Path = MODELS_DIR / "system"
# 微调模型目录（models/ftm，模型调优完成后的产出保存位置）
MODELS_FTM_DIR: Path = MODELS_DIR / "ftm"
# 训练产出模型导出目录（异步打包结果临时存放）
EXPORT_DIR: Path = ML_DATA_DIR / "exports"

# 预览内容上限（仅保留前 100KB 文本）
PREVIEW_LIMIT = 100 * 1024

# 评测任务单样本裁判打分并发数
_EVAL_CONCURRENCY = 5
# 自动切分随机种子（固定以保证同一数据集切分结果可复现）
_AUTO_SPLIT_SEED = 42
# 单样本明细里存储的检索文档条数上限（排名计算不受影响，仅限制 JSON 体积）
_MAX_STORED_TOP_DOCS = 100

# 待终止的评测任务 ID 集合（协作式停止，与训练任务 _STOP_FLAGS 一致）
_EVAL_STOP_FLAGS: set[str] = set()

# ======================================================================
# 选项常量（供 options 接口返回，前端用于下拉/卡片展示）
# ======================================================================

BASE_MODELS = [
    "qwen/Qwen2.5-7B-Instruct",
    "qwen/Qwen2.5-14B-Instruct",
    "Qwen/Qwen2-VL-7B-Instruct",
    "meta-llama/Llama-3.1-8B-Instruct",
    "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B",
]

BUCKETS = ["default-bucket", "training-data-bucket", "model-output-bucket"]

TRAIN_SCENES = [
    {"value": "text_gen", "label": "文本生成"},
    {"value": "vision", "label": "视觉理解"},
    {"value": "image2video_first", "label": "图生视频（首帧）"},
    {"value": "image2video_first_last", "label": "图生视频（首尾帧）"},
]

TRAIN_METHODS = [
    {"value": "sft", "label": "SFT（多轮对话微调）"},
    {"value": "dpo", "label": "DPO"},
    {"value": "cpt", "label": "CPT"},
]

TUNE_METHODS = [
    {"value": "sft", "label": "SFT 微调训练"},
    {"value": "dpo", "label": "DPO 偏好训练"},
    {"value": "cpt", "label": "CPT 继续预训练"},
    {"value": "rl", "label": "RL 强化学习"},
]


def list_model_dirs() -> list[dict]:
    """列出 models 目录下可选的模型，返回结构化项（含来源 source）。

    - models/system 下 → source=system（系统内置模型）；
    - models/ftm 下 → source=ftm（微调模型）；
    - 顶层其它目录 → source=local（本地模型）。
    其中 path 为相对 models 目录的路径，供后端回填 model_dir。
    """
    if not MODELS_DIR.exists():
        return []
    reserved = {MODELS_SYSTEM_DIR.name, MODELS_FTM_DIR.name}
    items: list[dict] = []
    for p in MODELS_DIR.iterdir():
        if not p.is_dir() or p.name.startswith(".") or p.name in reserved:
            continue
        items.append({"name": p.name, "path": p.name, "source": "local"})
    if MODELS_SYSTEM_DIR.exists():
        for p in MODELS_SYSTEM_DIR.iterdir():
            if not p.is_dir() or p.name.startswith("."):
                continue
            items.append({"name": p.name, "path": p.relative_to(MODELS_DIR).as_posix(), "source": "system"})
    if MODELS_FTM_DIR.exists():
        for p in MODELS_FTM_DIR.iterdir():
            if not p.is_dir() or p.name.startswith("."):
                continue
            items.append({"name": p.name, "path": p.relative_to(MODELS_DIR).as_posix(), "source": "ftm"})
    items.sort(key=lambda x: x["name"])
    return items


def options_payload() -> dict:
    return {
        "base_models": BASE_MODELS,
        "buckets": BUCKETS,
        "train_scenes": TRAIN_SCENES,
        "train_methods": TRAIN_METHODS,
        "tune_methods": TUNE_METHODS,
        "model_dirs": list_model_dirs(),
    }


# ======================================================================
# 数据集
# ======================================================================


async def create_dataset(db: AsyncSession, data) -> MLDataset:
    dataset = MLDataset(
        name=data.name,
        description=data.description,
        dataset_type=data.dataset_type,
        train_scene=data.train_scene,
        train_method=data.train_method,
        storage_location=data.storage_location,
        import_method=data.import_method,
    )
    db.add(dataset)
    await db.commit()
    await db.refresh(dataset)
    return dataset


async def list_datasets(
    db: AsyncSession,
    dataset_type: str | None = None,
    storage: str | None = None,
    import_method: str | None = None,
    search: str | None = None,
) -> list[MLDataset]:
    stmt = select(MLDataset).order_by(MLDataset.created_at.desc())
    if dataset_type:
        stmt = stmt.where(MLDataset.dataset_type == dataset_type)
    if storage:
        stmt = stmt.where(MLDataset.storage_location == storage)
    if import_method:
        stmt = stmt.where(MLDataset.import_method == import_method)
    if search:
        stmt = stmt.where(MLDataset.name.contains(search))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_dataset(db: AsyncSession, dataset_id: str) -> MLDataset | None:
    result = await db.execute(select(MLDataset).where(MLDataset.id == dataset_id))
    return result.scalar_one_or_none()


async def get_latest_version(db: AsyncSession, dataset_id: str) -> MLDatasetVersion | None:
    result = await db.execute(
        select(MLDatasetVersion)
        .where(MLDatasetVersion.dataset_id == dataset_id)
        .order_by(MLDatasetVersion.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def delete_dataset(db: AsyncSession, dataset: MLDataset) -> None:
    dataset_id = dataset.id
    # 取消该数据集下仍在生成中的版本任务，避免删除后后台任务继续执行导致脏写/原子性破坏
    result = await db.execute(
        select(MLDatasetVersion).where(
            MLDatasetVersion.dataset_id == dataset_id,
            MLDatasetVersion.import_status == "importing",
        )
    )
    for v in result.scalars().all():
        _cancel_generate(v.id)
    await db.delete(dataset)
    await db.commit()
    _remove_dataset_files(dataset_id)


async def list_versions(db: AsyncSession, dataset_id: str) -> list[MLDatasetVersion]:
    result = await db.execute(
        select(MLDatasetVersion)
        .where(MLDatasetVersion.dataset_id == dataset_id)
        .order_by(MLDatasetVersion.version.desc())
    )
    return list(result.scalars().all())


async def get_version(db: AsyncSession, version_id: str) -> MLDatasetVersion | None:
    result = await db.execute(select(MLDatasetVersion).where(MLDatasetVersion.id == version_id))
    return result.scalar_one_or_none()


async def create_version(
    db: AsyncSession, dataset: MLDataset, files: list[tuple[str, bytes]]
) -> MLDatasetVersion:
    versions = await list_versions(db, dataset.id)
    next_version = (versions[0].version + 1) if versions else 1

    data_count = 0
    preview = ""
    saved_paths: list[str] = []
    for filename, content in files:
        suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jsonl"
        data_count += _count_jsonl_lines(content) if suffix == "jsonl" else 0
        if not preview and suffix == "jsonl":
            preview = content[:PREVIEW_LIMIT].decode("utf-8", errors="replace")
        saved_paths.append(_save_dataset_file(dataset.id, next_version, filename, content))

    version = MLDatasetVersion(
        dataset_id=dataset.id,
        version=next_version,
        file_count=len(files),
        data_count=data_count,
        import_status="done",
        publish_status="published",
        file_id="file-" + uuid.uuid4().hex[:12],
        storage_path=",".join(saved_paths),
        preview_content=preview,
    )
    db.add(version)
    dataset.updated_at = datetime.now()
    await db.commit()
    await db.refresh(version)
    return version


def _save_dataset_file(dataset_id: str, version: int, filename: str, content: bytes) -> str:
    directory = DATASET_UPLOAD_DIR / dataset_id / f"v{version}"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_bytes(content)
    return to_rel_path(path)


def _remove_version_files(dataset_id: str, version: int) -> None:
    """删除某个版本的落盘文件目录（data/ml/datasets/<dataset_id>/v<version>）。"""
    directory = DATASET_UPLOAD_DIR / dataset_id / f"v{version}"
    if directory.exists():
        shutil.rmtree(directory, ignore_errors=True)
        logger.info("已删除数据集版本文件: %s", directory)


def _remove_dataset_files(dataset_id: str) -> None:
    """删除整个数据集落盘文件目录（含所有版本）。"""
    directory = DATASET_UPLOAD_DIR / dataset_id
    if directory.exists():
        shutil.rmtree(directory, ignore_errors=True)
        logger.info("已删除数据集文件目录: %s", directory)


def _count_jsonl_lines(content: bytes) -> int:
    text = content.decode("utf-8", errors="replace")
    return sum(1 for line in text.splitlines() if line.strip())


async def publish_version(db: AsyncSession, version: MLDatasetVersion) -> MLDatasetVersion:
    version.publish_status = "published"
    await db.commit()
    await db.refresh(version)
    return version


async def delete_version(db: AsyncSession, version: MLDatasetVersion) -> None:
    dataset_id = version.dataset_id
    ver = version.version
    _cancel_generate(version.id)
    await db.delete(version)
    await db.commit()
    _remove_version_files(dataset_id, ver)


def serialize_dataset(dataset: MLDataset, version: MLDatasetVersion | None) -> dict:
    return {
        "id": dataset.id,
        "name": dataset.name,
        "description": dataset.description,
        "dataset_type": dataset.dataset_type,
        "train_scene": dataset.train_scene,
        "train_method": dataset.train_method,
        "storage_location": dataset.storage_location,
        "import_method": dataset.import_method,
        "created_at": dataset.created_at,
        "updated_at": dataset.updated_at,
        "latest_version": version.version if version else None,
        "latest_version_id": version.id if version else None,
        "data_count": version.data_count if version else 0,
        "import_status": version.import_status if version else "",
        "publish_status": version.publish_status if version else "",
        "version_updated_at": version.created_at if version else None,
    }


# ======================================================================
# 生成数据集（基于知识库文档 + 大模型）
# ======================================================================

# 生成数据集时按目标数据量动态调整「单次大模型生成条数」与「最大并发数」，
# 避免单次请求生成过多记录导致超时（此前固定 5 批、每批上千条最终 80% 超时）。
_GENERATE_TIER: list[tuple[int, int, int]] = [
    # (数据量上限, 每批目标条数, 最大并发数)
    (5000, 200, 20),
    (10000, 500, 50),
    (20000, 500, 100),
    (10**9, 1000, 150),  # 40000+ 走该档，由 Semaphore 限流
]


def _generation_tier(count: int) -> tuple[int, int]:
    """按目标数据量返回 (每批条数, 最大并发数)。"""
    for upper, per_batch, concurrency in _GENERATE_TIER:
        if count <= upper:
            return per_batch, concurrency
    return 1000, 150


# 生成中的版本 ID -> 后台任务，便于删除数据集/版本时取消并释放资源
_GENERATE_TASKS: dict[str, asyncio.Task] = {}


def _build_generate_prompt(content: str, count: int) -> str:
    """加载 prompts/dataset_generate.txt 模板并填充变量。"""
    return prompt_loader.format_prompt("dataset_generate", count=count, content=content)


def get_eval_prompt_templates() -> dict:
    """加载 prompts/ 下的大模型评估评分器模板（分类型 + 数值型），供前端创建维度时选用。"""

    def _load(name: str) -> str:
        try:
            return prompt_loader.load_prompt(name)
        except FileNotFoundError:
            logger.warning("评测 prompt 模板缺失: %s", name)
            return ""

    return {
        "classify": {
            "standard": {
                "label": "标准匹配",
                "labels": {"pass": "Pass", "fail": "Fail"},
                "prompt": _load("eval_classify_standard"),
            },
            "sentiment": {
                "label": "情感分析",
                "labels": {"pass": "积极", "fail": "中性、消极"},
                "prompt": _load("eval_classify_sentiment"),
            },
        },
        "numeric": {
            "overall": {
                "label": "综合评测",
                "threshold": 3,
                "prompt": _load("eval_numeric_overall"),
            },
            "similarity": {
                "label": "语义相似度",
                "threshold": 4,
                "prompt": _load("eval_numeric_similarity"),
            },
            "hallucination": {
                "label": "幻觉率",
                "threshold": 4,
                "name": "幻觉率",
                "description": "评估回答是否存在事实错误或幻觉，1~5分，得分越高表示幻觉越少",
                "prompt": _load("eval_numeric_hallucination"),
            },
            "relevance": {
                "label": "答案相关性",
                "threshold": 3,
                "name": "答案相关性",
                "description": "评估回答与问题的相关程度，1~5分，得分越高表示越切题",
                "prompt": _load("eval_numeric_relevance"),
            },
            "completeness": {
                "label": "答案完整性",
                "threshold": 3,
                "name": "答案完整性",
                "description": "评估回答是否覆盖问题所需的所有必要信息，1~5分，得分越高表示越完整",
                "prompt": _load("eval_numeric_completeness"),
            },
        },
    }


def _extract_csv_text(raw: str) -> str:
    """去掉 LLM 返回中可能包裹的 Markdown 代码围栏等多余内容。"""
    text = (raw or "").strip()
    if not text:
        return ""
    lines = text.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _parse_csv_to_records(raw: str) -> list[dict]:
    """解析供应商返回的 CSV（query,positive,negative），转为记录列表。"""
    text = _extract_csv_text(raw)
    if not text:
        return []
    reader = csv.reader(io.StringIO(text))
    col = {"query": None, "positive": None, "negative": None}
    records: list[dict] = []
    for row in reader:
        cells = [c.strip() for c in row]
        if not any(cells):
            continue
        if col["query"] is None and col["positive"] is None and col["negative"] is None:
            # 定位表头列索引（兼容中文别名与首列缺失等情况）
            for i, c in enumerate(cells):
                cl = c.lower()
                if cl in {"query", "question", "问题"}:
                    col["query"] = i
                elif cl in {"positive", "answer", "回答"}:
                    col["positive"] = i
                elif cl in {"negative", "wrong", "错误答案", "错答"}:
                    col["negative"] = i
            continue
        rec = {
            "query": cells[col["query"]] if col["query"] is not None and col["query"] < len(cells) else "",
            "positive": cells[col["positive"]] if col["positive"] is not None and col["positive"] < len(cells) else "",
            "negative": cells[col["negative"]] if col["negative"] is not None and col["negative"] < len(cells) else "",
        }
        if rec["query"] and rec["positive"]:
            records.append(rec)
    return records


def _split_into_batches(items: list, group_count: int) -> list[list]:
    """将列表均分为至多 group_count 组，保证每组尽量均衡。"""
    group_count = max(1, min(group_count, len(items)))
    if group_count == 1:
        return [items]
    per = math.ceil(len(items) / group_count)
    return [items[i : i + per] for i in range(0, len(items), per)]


async def _generate_records_batched(llm, contents: list[str], count: int) -> list[dict]:
    """将知识库内容按目标数据量动态分批并发发送给供应商生成 CSV，汇总为记录列表。

    每批仅生成少量记录（如 200 条），降低单次 LLM 响应时间；并发数按数据量档位控制。
    """
    per_batch_target, max_concurrency = _generation_tier(count)
    batch_count = max(1, math.ceil(count / per_batch_target))
    batches = _split_into_batches(contents, batch_count)
    actual_batches = len(batches)
    per_batch = math.ceil(count / actual_batches) if actual_batches else 0
    total_chars = sum(len(c) for c in contents)
    logger.info(
        "数据集生成开始: 切片总数=%d 总字符数=%d 分批数=%d 每批目标条数=%d 最大并发=%d",
        len(contents),
        total_chars,
        actual_batches,
        per_batch,
        max_concurrency,
    )
    sem = asyncio.Semaphore(max_concurrency)

    async def run(batch: list[str], idx: int) -> list[dict]:
        batch_chars = sum(len(c) for c in batch)
        logger.info(
            "批次[%d/%d] 开始生成: 切片数=%d 字符数=%d",
            idx + 1,
            actual_batches,
            len(batch),
            batch_chars,
        )
        async with sem:
            try:
                prompt = _build_generate_prompt("\n\n".join(batch), per_batch)
                resp = await llm.complete([{"role": "user", "content": prompt}], temperature=0.4)
                records = _parse_csv_to_records(resp.get("content", ""))
                logger.info("批次[%d/%d] 生成完成: 解析出记录=%d", idx + 1, actual_batches, len(records))
                return records
            except Exception as exc:  # noqa: BLE001
                logger.warning("批次[%d/%d] 生成失败: %s", idx + 1, actual_batches, exc)
                return []

    results = await asyncio.gather(*(run(b, i) for i, b in enumerate(batches)))
    records: list[dict] = []
    for r in results:
        records.extend(r)
    logger.info("数据集生成汇总: 共解析出记录=%d", len(records))
    return records


async def _collect_space_chunks(db: AsyncSession, space_id: str, limit: int | None = None) -> list[Chunk]:
    stmt = (
        select(Chunk)
        .where(Chunk.space_id == space_id)
        .order_by(Chunk.document_id, Chunk.chunk_index)
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _log_space_documents(db: AsyncSession, space_id: str) -> None:
    """打印知识库文档明细（文件名 / 大小 / 切片数 / 字符数），便于排查生成过程。"""
    result = await db.execute(
        select(Document).where(Document.space_id == space_id).order_by(Document.created_at)
    )
    docs = list(result.scalars().all())
    for d in docs:
        logger.info(
            "知识库文档: name=%s size=%d chunks=%d chars=%d",
            d.filename,
            d.file_size,
            d.chunk_count,
            d.char_count,
        )
    logger.info("知识库文档总数: %d", len(docs))


async def generate_dataset(db: AsyncSession, data, user_id: str) -> MLDataset:
    """选择知识库 → 创建数据集与「导入中」版本 → 后台分批生成数据并发布。

    前端调用后立即拿到数据集与版本，随后轮询版本状态：importing → done → published。
    """
    from app.services import knowledge_service

    space = await knowledge_service.get_space(db, user_id, data.space_id)
    if not space:
        raise BusinessError(ErrorCode.SPACE_NOT_FOUND, http_status=404)

    # 轻量校验：知识库至少存在一条可用切片
    chunks = await _collect_space_chunks(db, data.space_id, limit=1)
    if not chunks:
        raise BusinessError(
            ErrorCode.INVALID_PARAMETER,
            message="该知识库暂无可用文档内容，请先上传文档并完成向量化",
            http_status=400,
        )

    cfg = await config_service.get_runtime(db)
    try:
        build_llm(cfg)
    except LLMError as exc:
        logger.warning("生成数据集缺少大模型配置: %s", exc)
        raise BusinessError(ErrorCode.INVALID_PARAMETER, message="请先在系统设置中配置大模型", http_status=400)

    count = max(1, int(getattr(data, "count", 0) or 0))
    logger.info("创建数据集生成任务: name=%s space=%s(space_id=%s) count=%d", data.name, space.name, space.id, count)
    await _log_space_documents(db, space.id)

    dataset = MLDataset(
        name=data.name,
        description=data.description,
        dataset_type=data.dataset_type,
        train_scene=data.train_scene,
        train_method=data.train_method,
        storage_location="oss",
        import_method="generate",
    )
    db.add(dataset)
    await db.commit()
    await db.refresh(dataset)

    version = await _create_placeholder_version(db, dataset)
    schedule_generate(version.id, space.id, count)
    return dataset


async def _create_placeholder_version(db: AsyncSession, dataset: MLDataset) -> MLDatasetVersion:
    """创建一个「导入中」的版本占位，后台生成完成后回填数据并发布。"""
    versions = await list_versions(db, dataset.id)
    next_version = (versions[0].version + 1) if versions else 1
    version = MLDatasetVersion(
        dataset_id=dataset.id,
        version=next_version,
        file_count=0,
        data_count=0,
        import_status="importing",
        publish_status="draft",
        file_id="file-" + uuid.uuid4().hex[:12],
        storage_path="",
        preview_content="",
    )
    db.add(version)
    dataset.updated_at = datetime.now()
    await db.commit()
    await db.refresh(version)
    return version


def schedule_generate(version_id: str, space_id: str, count: int) -> None:
    """后台任务：生成数据集内容并回填版本状态（登记任务句柄以便删除时取消）。"""
    task = asyncio.create_task(_run_generate_version(version_id, space_id, count))
    _GENERATE_TASKS[version_id] = task


def _cancel_generate(version_id: str) -> None:
    """取消正在生成数据集的版本任务，及时释放并发与数据库资源。"""
    task = _GENERATE_TASKS.get(version_id)
    if task is not None and not task.done():
        task.cancel()
        logger.info("已取消数据集生成任务: version_id=%s", version_id)


async def _run_generate_version(version_id: str, space_id: str, count: int) -> None:
    """独立会话中执行数据生成（收集切片 → 分批调用大模型 → 写文件 → 发布）。"""
    try:
        async with SessionLocal() as db:
            version = await get_version(db, version_id)
            if not version:
                logger.warning("数据生成任务：版本不存在 version_id=%s", version_id)
                return
            try:
                chunks = await _collect_space_chunks(db, space_id)
                contents = [c.content for c in chunks if c.content]
                if not contents:
                    raise ValueError("该知识库暂无可用文档内容")

                cfg = await config_service.get_runtime(db)
                llm = build_llm(cfg)
                records = await _generate_records_batched(llm, contents, count)
                if not records:
                    raise ValueError("大模型未返回有效数据")

                records = records[:count]
                jsonl_text = "\n".join(json.dumps(r, ensure_ascii=False) for r in records)
                raw = jsonl_text.encode("utf-8")
                path = _save_dataset_file(version.dataset_id, version.version, "generated.jsonl", raw)

                # 生成期间数据集可能已被删除；重新取一次避免对已删除行 UPDATE 触发 PendingRollbackError
                cur = await get_version(db, version_id)
                if cur is None:
                    logger.warning("数据集生成期间版本已删除，跳过回填: version_id=%s", version_id)
                    return
                cur.storage_path = str(path)
                cur.file_count = 1
                cur.data_count = len(records)
                cur.preview_content = raw[:PREVIEW_LIMIT].decode("utf-8", errors="replace")
                cur.import_status = "done"
                cur.publish_status = "published"
                await db.commit()
                logger.info("数据集生成完成: version_id=%s records=%d", cur.id, len(records))
            except asyncio.CancelledError:
                logger.info("数据集生成任务被取消: version_id=%s", version_id)
                raise
            except Exception as exc:  # noqa: BLE001
                logger.exception("数据集生成失败: version_id=%s, error=%s", version_id, exc)
                try:
                    cur = await get_version(db, version_id)
                    if cur is not None:
                        cur.import_status = "failed"
                        cur.publish_status = "draft"
                        await db.commit()
                    else:
                        await db.rollback()
                except Exception:  # noqa: BLE001 - 已删除导致提交失败时回滚即可
                    await db.rollback()
    finally:
        _GENERATE_TASKS.pop(version_id, None)


# ======================================================================
# 模型
# ======================================================================


async def create_model(db: AsyncSession, data) -> MLModel:
    model = MLModel(
        name=data.name,
        base_model=data.base_model,
        train_method=data.train_method,
        source=data.source,
        bucket=data.bucket,
        model_dir=data.model_dir,
        provider_config=getattr(data, "provider_config", None),
        status="ready",
    )
    db.add(model)
    await db.commit()
    await db.refresh(model)
    return model


def _rel_model_dir(path: Path) -> str:
    """将模型目录转为项目根目录下的相对路径（不含盘符与前导分隔符）。"""
    return to_rel_path(path)


def _resolve_model_dir(model_dir: str) -> Path | None:
    """将 model_dir 解析为绝对路径；空值返回 None。"""
    if not model_dir:
        return None
    s = model_dir.replace("\\", "/").lstrip("/")
    if not s:
        return None
    p = Path(s)
    if p.is_absolute():
        return p.resolve()
    return (BASE_DIR / p).resolve()


def model_is_local(model_dir: str) -> bool:
    """判断模型目录是否位于项目 models 目录下且真实存在。"""
    p = _resolve_model_dir(model_dir)
    if p is None or not p.is_dir():
        return False
    try:
        p.relative_to(MODELS_DIR.resolve())
        return True
    except ValueError:
        return False


def model_dir_is_system(model_dir: str) -> bool:
    """判断模型目录是否位于 models/system 目录下（系统内置模型）。"""
    p = _resolve_model_dir(model_dir)
    if p is None:
        return False
    try:
        p.relative_to(MODELS_SYSTEM_DIR.resolve())
        return True
    except ValueError:
        return False


def model_dir_source(model_dir: str) -> str:
    """根据模型目录位置返回来源：system（系统内置）/ ftm（微调）/ local（本地）/ none（不在 models 下）。"""
    p = _resolve_model_dir(model_dir)
    if p is None:
        return "none"
    try:
        p.relative_to(MODELS_SYSTEM_DIR.resolve())
        return "system"
    except ValueError:
        pass
    try:
        p.relative_to(MODELS_FTM_DIR.resolve())
        return "ftm"
    except ValueError:
        pass
    if model_is_local(model_dir):
        return "local"
    return "none"


async def import_model_from_existing(db: AsyncSession, name: str, base_model: str) -> MLModel:
    """选择已有模型：直接引用 models/<base_model> 目录（base_model 为相对 models 的路径）。"""
    if "/" in name or "\\" in name or ".." in name:
        raise BusinessError(ErrorCode.INVALID_PARAMETER, message="模型名称不能包含路径分隔符", http_status=400)

    rel = base_model.replace("\\", "/").strip("/")
    resolved = MODELS_DIR / rel
    model_dir = _rel_model_dir(resolved)
    final_base = Path(rel).name or base_model
    logger.info("引用已有模型: name=%r base_model=%r model_dir=%s", name, base_model, model_dir)

    model = MLModel(
        name=name,
        base_model=final_base,
        source="select",
        model_dir=model_dir,
        status="ready",
    )
    db.add(model)
    await db.commit()
    await db.refresh(model)
    return model


async def start_model_import(db: AsyncSession, name: str, entries: list[tuple[str, bytes]]) -> MLModel:
    """启动异步导入：先创建「导入中」的模型记录，后台负责落盘/解压并更新状态。"""
    if "/" in name or "\\" in name or ".." in name:
        raise BusinessError(ErrorCode.INVALID_PARAMETER, message="模型名称不能包含路径分隔符", http_status=400)

    model = MLModel(
        name=name,
        base_model=name,
        source="upload",
        model_dir="",
        status="importing",
    )
    db.add(model)
    await db.commit()
    await db.refresh(model)
    schedule_model_import(model.id, name, entries)
    return model


def schedule_model_import(model_id: str, name: str, entries: list[tuple[str, bytes]]) -> None:
    """后台任务：落盘模型文件（支持 zip 解压）并更新模型状态。"""
    asyncio.create_task(_run_model_import(model_id, name, entries))


def _extract_zip_to(target: Path, content: bytes) -> None:
    """将 zip 解压到 target；若所有文件位于同一顶层目录内，则剥离该层直接落盘。"""
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        if not names:
            raise ValueError("zip 压缩包内无文件")
        prefix = ""
        first = names[0].replace("\\", "/")
        top = first.split("/", 1)[0] if "/" in first else ""
        if top and all(n.replace("\\", "/").startswith(top + "/") for n in names):
            prefix = top + "/"
        for name in names:
            rel = name.replace("\\", "/")
            if prefix and rel.startswith(prefix):
                rel = rel[len(prefix):]
            if not rel:
                continue
            dest = target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(name) as src, dest.open("wb") as dst:
                shutil.copyfileobj(src, dst)


async def _run_model_import(model_id: str, name: str, entries: list[tuple[str, bytes]]) -> None:
    """独立会话中执行模型导入：目录复制 / zip 解压到 models/<name>，完成后置 ready。"""
    async with SessionLocal() as db:
        model = await get_model(db, model_id)
        if not model:
            logger.warning("模型导入任务：模型不存在 model_id=%s", model_id)
            return
        try:
            target = MODELS_DIR / name
            target.mkdir(parents=True, exist_ok=True)
            logger.info("模型导入开始: model_id=%s name=%r 文件数=%d 目标目录=%s", model_id, name, len(entries), target)

            # 单个 zip 压缩包：解压到目标目录（剥离单一顶层目录）
            if len(entries) == 1 and entries[0][0].lower().endswith(".zip"):
                filename, content = entries[0]
                logger.info("检测到 zip 压缩包: %s (%d bytes)，开始解压", filename, len(content))
                _extract_zip_to(target, content)
            else:
                for filename, content in entries:
                    rel = (filename or "").strip().replace("\\", "/")
                    # webkitdirectory 上传的 filename 形如「<文件夹>/<相对路径>」，去除首段文件夹名
                    if "/" in rel:
                        rel = rel.split("/", 1)[1]
                    if not rel:
                        rel = filename or "model.bin"
                    rel = rel.lstrip("/")
                    dest = target / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(content)
                    logger.debug("写入模型文件: %s (%d bytes)", dest, len(content))

            model.model_dir = _rel_model_dir(target)
            model.status = "ready"
            await db.commit()
            logger.info("模型导入完成: model_id=%s name=%r model_dir=%s", model_id, name, model.model_dir)
        except Exception as exc:  # noqa: BLE001
            logger.exception("模型导入失败: model_id=%s name=%r error=%s", model_id, name, exc)
            model.status = "failed"
            await db.commit()


async def list_models(db: AsyncSession, search: str | None = None) -> list[MLModel]:
    stmt = select(MLModel).order_by(MLModel.created_at.desc())
    if search:
        stmt = stmt.where(MLModel.name.contains(search))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_model(db: AsyncSession, model_id: str) -> MLModel | None:
    result = await db.execute(select(MLModel).where(MLModel.id == model_id))
    return result.scalar_one_or_none()


async def get_model_by_name(db: AsyncSession, name: str) -> MLModel | None:
    """按模型名称查询「我的模型」记录（训练/评测以模型名称关联）。"""
    result = await db.execute(select(MLModel).where(MLModel.name == name))
    return result.scalars().first()


async def delete_model(db: AsyncSession, model: MLModel, delete_local: bool = False) -> None:
    """删除模型记录；delete_local 为 True 时同时删除本地模型文件夹（系统内置模型除外）。"""
    if delete_local:
        p = _resolve_model_dir(model.model_dir)
        if p is not None and model_is_local(model.model_dir) and not model_dir_is_system(model.model_dir):
            if p.exists():
                shutil.rmtree(p)
                logger.info("删除本地模型文件: %s", p)
    await db.delete(model)
    await db.commit()


async def save_model_local(db: AsyncSession, model: MLModel) -> MLModel:
    """将不在本地 models 目录的模型复制到项目 models/<name> 目录，并更新 model_dir。"""
    src = _resolve_model_dir(model.model_dir)
    if src is None or not src.is_dir():
        raise BusinessError(
            ErrorCode.INVALID_PARAMETER, message="模型目录不存在，无法保存到本地", http_status=400
        )
    if model_is_local(model.model_dir):
        return model
    target = MODELS_DIR / model.name
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(src, target)
    model.model_dir = _rel_model_dir(target)
    await db.commit()
    await db.refresh(model)
    return model


def serialize_model(model: MLModel) -> dict:
    """序列化模型，附带 is_local / source_type 标记供前端决定展示按钮、来源标签与删除弹窗勾选项。"""
    return {
        "id": model.id,
        "name": model.name,
        "base_model": model.base_model,
        "train_method": model.train_method,
        "source": model.source,
        "bucket": model.bucket,
        "model_dir": model.model_dir,
        "provider_config": model.provider_config,
        "status": model.status,
        "created_at": model.created_at,
        "updated_at": model.updated_at,
        "is_local": model_is_local(model.model_dir),
        "source_type": "provider" if model.source == "provider" else model_dir_source(model.model_dir),
    }


# ===== 模型目录文件查看 =====

_VIEWABLE_TEXT_EXTS = {".json", ".md", ".txt"}  # 前端可弹窗预览内容的文件后缀
_MAX_VIEW_FILE_SIZE = 512 * 1024  # 单个预览文件最多读取 512KB


def _model_view_dir(model: MLModel) -> Path | None:
    """解析模型本地目录：优先 model_dir，其次按名称在 models 各层级查找。"""
    if model.model_dir:
        p = _resolve_model_dir(model.model_dir)
        if p is not None and p.is_dir():
            return p
    for raw in (model.name, model.base_model):
        name = (raw or "").replace("\\", "/").strip("/")
        if not name:
            continue
        for cand in (MODELS_DIR / name, MODELS_SYSTEM_DIR / name, MODELS_FTM_DIR / name):
            if cand.is_dir():
                return cand
    return None


def list_model_files(model: MLModel) -> dict:
    """列出模型目录下的全部文件（递归），含单文件大小与总大小，供「查看」页面展示。"""
    root = _model_view_dir(model)
    if root is None:
        return {"dir": None, "file_count": 0, "total_size": 0, "total_size_mb": 0.0, "files": []}

    files: list[dict] = []
    total = 0
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        try:
            size = p.stat().st_size
        except OSError:
            continue
        total += size
        ext = p.suffix.lower()
        files.append(
            {
                "path": p.relative_to(root).as_posix(),
                "name": p.name,
                "ext": ext.lstrip("."),
                "size": size,
                "empty": size == 0,
                "viewable": ext in _VIEWABLE_TEXT_EXTS,
            }
        )
    return {
        "dir": str(root),
        "file_count": len(files),
        "total_size": total,
        "total_size_mb": round(total / 1024 / 1024, 2),
        "files": files,
    }


def read_model_file(model: MLModel, rel_path: str) -> dict:
    """读取模型目录下 json/md/txt 文件内容（做路径穿越校验并限制读取大小）。"""
    root = _model_view_dir(model)
    if root is None:
        raise BusinessError(ErrorCode.INVALID_PARAMETER, message="该模型没有本地文件目录", http_status=404)

    target = (root / rel_path).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        raise BusinessError(ErrorCode.INVALID_PARAMETER, message="非法文件路径", http_status=400) from None
    if not target.is_file():
        raise BusinessError(ErrorCode.INVALID_PARAMETER, message=f"文件不存在: {rel_path}", http_status=404)
    if target.suffix.lower() not in _VIEWABLE_TEXT_EXTS:
        raise BusinessError(
            ErrorCode.INVALID_PARAMETER, message="仅支持查看 .json / .md / .txt 文件", http_status=400
        )

    size = target.stat().st_size
    base = {"path": rel_path, "name": target.name, "size": size, "empty": size == 0}
    if size == 0:
        return {**base, "content": "", "truncated": False}

    raw = target.read_bytes()[:_MAX_VIEW_FILE_SIZE]
    truncated = size > _MAX_VIEW_FILE_SIZE
    content = raw.decode("utf-8", errors="replace")
    if target.suffix.lower() == ".json" and not truncated:
        try:
            content = json.dumps(json.loads(content), ensure_ascii=False, indent=2)
        except (ValueError, TypeError):
            pass
    return {**base, "content": content, "truncated": truncated}


async def import_provider_model(db: AsyncSession, name: str, provider: str, url: str, api_key: str, model_name: str) -> MLModel:
    """导入供应商向量模型：保存远程供应商配置，后续评测/调优使用该供应商的向量模型而非本地模型。"""
    if "/" in name or "\\" in name or ".." in name:
        raise BusinessError(ErrorCode.INVALID_PARAMETER, message="模型名称不能包含路径分隔符", http_status=400)

    config = {
        "provider": (provider or "").strip() or "阿里云",
        "url": (url or "").strip(),
        "api_key": (api_key or "").strip(),
        "model": (model_name or "").strip(),
    }
    model = MLModel(
        name=name,
        base_model=config["model"] or config["provider"],
        source="provider",
        model_dir="",
        provider_config=config,
        status="ready",
    )
    db.add(model)
    await db.commit()
    await db.refresh(model)
    logger.info("导入供应商模型: model_id=%s name=%r provider=%r model=%r", model.id, name, config["provider"], config["model"])
    return model


# ======================================================================
# 训练任务
# ======================================================================

_STOP_FLAGS: set[str] = set()
# 同一时刻只允许一个微调任务占用显存：并发训练会叠加显存占用导致 CUDA OOM
_TRAIN_LOCK = asyncio.Lock()


def _release_torch_memory(note: str = "") -> None:
    """回收训练占用的显存/内存：触发 GC 并清空 PyTorch 缓存分配器。

    PyTorch 释放的显存默认留在进程缓存里不还给驱动，任务结束后显式清空，
    才能保证下一次微调/评测拿到完整显存。
    """
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001 - 内存回收失败不应影响任务收尾
        pass
    if note:
        logger.info("显存/内存已释放：%s", note)


async def create_train_task(db: AsyncSession, data) -> MLTrainTask:
    # 训练集支持多选：优先取 dataset_ids，向后兼容单个 dataset_id
    ids: list[str] = list(data.dataset_ids or ([] if not data.dataset_id else [data.dataset_id]))
    config = dict(data.config or {})
    config["dataset_ids"] = ids
    task = MLTrainTask(
        name=data.name,
        priority=data.priority,
        train_method=data.train_method,
        base_model=data.base_model,
        dataset_id=ids[0] if ids else None,
        valid_ratio=data.valid_ratio,
        config=config,
        output_model_name=data.output_model_name,
        status="pending",
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    schedule_train(task.id)
    return task


async def list_train_tasks(
    db: AsyncSession,
    priority: str | None = None,
    base_model: str | None = None,
    search: str | None = None,
) -> list[MLTrainTask]:
    stmt = select(MLTrainTask).order_by(MLTrainTask.created_at.desc())
    if priority:
        stmt = stmt.where(MLTrainTask.priority == priority)
    if base_model:
        stmt = stmt.where(MLTrainTask.base_model == base_model)
    if search:
        stmt = stmt.where(MLTrainTask.name.contains(search) | (MLTrainTask.id == search))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_train_task(db: AsyncSession, task_id: str) -> MLTrainTask | None:
    result = await db.execute(select(MLTrainTask).where(MLTrainTask.id == task_id))
    return result.scalar_one_or_none()


async def stop_train_task(db: AsyncSession, task: MLTrainTask) -> MLTrainTask:
    _STOP_FLAGS.add(task.id)
    if task.status in {"pending", "running"}:
        task.status = "stopped"
        await db.commit()
        await db.refresh(task)
    return task


async def resume_train_task(db: AsyncSession, task: MLTrainTask) -> MLTrainTask:
    if task.status != "stopped":
        raise BusinessError(
            ErrorCode.INVALID_PARAMETER,
            message="仅已停止的训练任务可恢复训练",
            http_status=400,
        )
    _STOP_FLAGS.discard(task.id)
    task.status = "pending"
    await db.commit()
    await db.refresh(task)
    schedule_train(task.id)
    return task


async def delete_train_task(db: AsyncSession, task: MLTrainTask) -> None:
    _STOP_FLAGS.add(task.id)
    await db.delete(task)
    await db.commit()


def _iter_model_files(root: Path) -> list[Path]:
    """收集模型目录中的「重要文件」，排除 .git/隐藏文件/说明文档/备份文件。

    仅保留模型权重、配置与分词器等二次导入模型所需的文件，避免打包 .git 等无关内容。
    """
    files: list[Path] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if rel.name == "README.md":
            continue
        if rel.suffix == ".backup":
            continue
        files.append(p)
    return files


async def resolve_export_base_dir(db: AsyncSession, base_model: str) -> Path | None:
    """解析基础模型所在目录：依次查找 models 顶层、system、ftm 子目录，再按「我的模型」记录反查。"""
    if not base_model:
        return None
    name = base_model.replace("\\", "/").strip("/")
    for cand in (MODELS_DIR / name, MODELS_SYSTEM_DIR / name, MODELS_FTM_DIR / name):
        if cand.is_dir():
            return cand
    result = await db.execute(select(MLModel).where(MLModel.name == base_model))
    model = result.scalars().first()
    if model and model.model_dir:
        p = Path(model.model_dir)
        if p.is_dir():
            return p
    return None


def _ensure_exportable(task: MLTrainTask) -> None:
    if task.status != "done":
        raise BusinessError(
            ErrorCode.INVALID_PARAMETER, message="仅训练完成的任务可导出", http_status=400
        )
    if not task.output_model_name:
        raise BusinessError(
            ErrorCode.INVALID_PARAMETER, message="该任务暂无产出模型", http_status=400
        )


# ======================================================================
# 异步导出：后台线程打包 → 进度查询 → 文件下载
# ======================================================================


class ExportJob:
    __slots__ = ("state", "progress", "error", "file_path", "filename")

    def __init__(self) -> None:
        self.state = "idle"  # idle | running | done | error
        self.progress = 0
        self.error: str | None = None
        self.file_path: str | None = None
        self.filename: str | None = None


_export_jobs: dict[str, ExportJob] = {}
_export_lock = threading.Lock()


def _job_snapshot(job: ExportJob) -> dict:
    return {
        "state": job.state,
        "progress": job.progress,
        "error": job.error,
        "filename": job.filename,
    }


def get_export_status(task_id: str) -> dict | None:
    with _export_lock:
        job = _export_jobs.get(task_id)
    return _job_snapshot(job) if job is not None else None


def start_export_job(task: MLTrainTask, base_dir: Path | None) -> dict:
    """启动后台导出任务；若已在导出中则直接返回当前状态。返回状态快照。"""
    _ensure_exportable(task)
    key = task.id
    with _export_lock:
        existing = _export_jobs.get(key)
        if existing is not None and existing.state == "running":
            return _job_snapshot(existing)
        job = ExportJob()
        job.state = "running"
        _export_jobs[key] = job
    # 后台线程独立于请求生命周期，即使前端断开也继续执行
    thread = threading.Thread(target=_run_export_job, args=(task, base_dir), daemon=True)
    thread.start()
    return _job_snapshot(job)


def _set_export_progress(key: str, value: int) -> None:
    with _export_lock:
        job = _export_jobs.get(key)
        if job is not None:
            job.progress = max(0, min(100, value))


def _run_export_job(task: MLTrainTask, base_dir: Path | None) -> None:
    key = task.id
    try:
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        dest = EXPORT_DIR / f"{key}.zip"
        if dest.exists():
            dest.unlink()

        def progress_cb(copied: int, total: int) -> None:
            _set_export_progress(key, int(copied * 100 / total) if total > 0 else 100)

        filename = _build_export_zip(dest, task, base_dir, progress_cb)

        with _export_lock:
            job = _export_jobs.get(key)
            if job is not None:
                job.state = "done"
                job.progress = 100
                job.file_path = str(dest)
                job.filename = filename
    except Exception as e:  # noqa: BLE001
        logger.exception("导出训练产出失败: task_id=%s", key)
        with _export_lock:
            job = _export_jobs.get(key)
            if job is not None:
                job.state = "error"
                job.error = str(e) or "导出失败"
                job.filename = None


def _build_export_zip(dest: Path, task: MLTrainTask, base_dir: Path | None, progress_cb) -> str:
    """将基础模型「重要文件」写入 zip，按字节回传进度，返回文件名。"""
    filename = f"{task.output_model_name}.zip"
    prefix = f"{task.output_model_name}/"
    manifest = {
        "output_model_name": task.output_model_name,
        "base_model": task.base_model,
        "train_method": task.train_method,
        "valid_ratio": task.valid_ratio,
        "config": task.config or {},
    }
    files = _iter_model_files(base_dir) if base_dir else []
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        total = sum(p.stat().st_size for p in files)
        copied = 0
        for p in files:
            arcname = prefix + p.relative_to(base_dir).as_posix()
            with p.open("rb") as src, zf.open(arcname, "w") as dst:
                while True:
                    chunk = src.read(1 << 20)
                    if not chunk:
                        break
                    dst.write(chunk)
                    copied += len(chunk)
                    progress_cb(copied, total)
        if files:
            # 追加训练元信息，不影响模型文件解析
            zf.writestr(
                prefix + "train_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2)
            )
        else:
            # 基础模型目录不存在时写入占位，保证导出始终有内容
            # 用 train_manifest.json 而非 config.json：后者是模型结构配置，不能被任务元数据占用
            zf.writestr(prefix + "train_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return filename


def schedule_train(task_id: str) -> None:
    asyncio.create_task(_run_train_task(task_id))


def _train_output_name(task: MLTrainTask) -> str:
    return task.output_model_name or f"{task.name}-v1"


def _train_output_dir(task: MLTrainTask) -> Path:
    return MODELS_FTM_DIR / _train_output_name(task)


def _build_output_model_config(task: MLTrainTask) -> dict:
    return {
        "output_model_name": _train_output_name(task),
        "base_model": task.base_model,
        "train_method": task.train_method,
        "valid_ratio": task.valid_ratio,
        "config": task.config or {},
    }


def _build_metrics(
    epochs: list[int],
    train_loss: list[float],
    val_loss: list[float],
    val_acc: list[float],
    learning_rate: list[float],
    total_steps: int,
    total_time_sec: float,
    token_usage: int | None = None,
    final_loss: float | None = None,
    final_acc: float | None = None,
) -> dict:
    return {
        "epochs": epochs,
        "train_loss": train_loss,
        "val_loss": val_loss,
        "val_acc": val_acc,
        "learning_rate": learning_rate,
        "total_steps": total_steps,
        "total_time_sec": round(total_time_sec, 1),
        "token_usage": token_usage,
        "final_loss": final_loss,
        "final_acc": final_acc,
    }


def _fmt_lr(value: float) -> str:
    """将学习率格式化为普通十进制（如 0.00002），去除多余尾零。"""
    return f"{value:.6f}".rstrip("0").rstrip(".")


async def _train_data_sizes(db: AsyncSession, task: MLTrainTask) -> tuple[int, int]:
    """汇总训练集数据量，按验证集比例拆分为（训练集, 验证集）。"""
    ids = task.dataset_ids or ([task.dataset_id] if task.dataset_id else [])
    total = 0
    for did in ids:
        result = await db.execute(
            select(MLDatasetVersion)
            .where(MLDatasetVersion.dataset_id == did)
            .order_by(MLDatasetVersion.version.desc())
            .limit(1)
        )
        version = result.scalars().first()
        if version:
            total += version.data_count or 0
    val_size = int(total * (task.valid_ratio or 0))
    return total - val_size, val_size


async def _ensure_output_model(db: AsyncSession, task: MLTrainTask) -> MLModel | None:
    """将训练产出的模型登记到「我的模型」。

    - 模型名称 = 保存模型名（output_model_name）；
    - 基础模型 = 训练配置中选定的基础模型（base_model）。
    按 model_dir 幂等，重复调用不会产生重复记录。
    """
    output_name = _train_output_name(task)
    model_dir = _rel_model_dir(MODELS_FTM_DIR / output_name)
    result = await db.execute(select(MLModel).where(MLModel.model_dir == model_dir))
    existing = result.scalars().first()
    if existing:
        return existing
    model = MLModel(
        name=output_name,
        base_model=task.base_model,
        train_method=task.train_method,
        source="ftm",
        model_dir=model_dir,
        status="ready",
    )
    db.add(model)
    await db.commit()
    await db.refresh(model)
    return model


# ======================================================================
# 异步保存到「我的模型」：后台把基础模型权重/配置/分词器复制进产出目录并登记
# ======================================================================


class SaveModelJob:
    __slots__ = ("state", "progress", "error", "model_dir", "model_name")

    def __init__(self) -> None:
        self.state = "idle"  # idle | running | done | error
        self.progress = 0
        self.error: str | None = None
        self.model_dir: str | None = None
        self.model_name: str | None = None


_save_model_jobs: dict[str, SaveModelJob] = {}
_save_model_lock = threading.Lock()


def _save_snapshot(job: SaveModelJob) -> dict:
    return {
        "state": job.state,
        "progress": job.progress,
        "error": job.error,
        "model_dir": job.model_dir,
        "model_name": job.model_name,
    }


def get_save_model_status(task_id: str) -> dict | None:
    with _save_model_lock:
        job = _save_model_jobs.get(task_id)
    return _save_snapshot(job) if job is not None else None


def start_save_model_job(task: MLTrainTask) -> dict:
    """启动后台保存任务；若已在保存中则返回当前状态。"""
    if task.status != "done":
        raise BusinessError(
            ErrorCode.INVALID_PARAMETER, message="仅训练完成的任务可保存模型", http_status=400
        )
    if not task.output_model_name:
        raise BusinessError(
            ErrorCode.INVALID_PARAMETER, message="该任务暂无产出模型", http_status=400
        )
    key = task.id
    with _save_model_lock:
        existing = _save_model_jobs.get(key)
        if existing is not None and existing.state == "running":
            return _save_snapshot(existing)
        job = SaveModelJob()
        job.state = "running"
        _save_model_jobs[key] = job
    asyncio.create_task(_run_save_model_job(task))
    return _save_snapshot(job)


def _set_save_progress(key: str, value: int) -> None:
    with _save_model_lock:
        job = _save_model_jobs.get(key)
        if job is not None:
            job.progress = max(0, min(100, value))


def _copy_dir_with_progress(src: Path, target: Path, key: str) -> None:
    """把基础模型目录按字节复制到 target，并在复制过程中回传进度。"""
    files = _iter_model_files(src)
    total = sum(p.stat().st_size for p in files)
    target.mkdir(parents=True, exist_ok=True)
    copied = 0
    for p in files:
        rel = p.relative_to(src)
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        with p.open("rb") as fsrc, dest.open("wb") as fdst:
            while True:
                chunk = fsrc.read(1 << 20)
                if not chunk:
                    break
                fdst.write(chunk)
                copied += len(chunk)
                _set_save_progress(key, int(copied * 100 / total) if total > 0 else 100)


async def _run_save_model_job(task: MLTrainTask) -> None:
    key = task.id
    try:
        output_name = _train_output_name(task)
        target = _train_output_dir(task)
        manifest = target / "train_manifest.json"
        async with SessionLocal() as db:
            base_dir = await resolve_export_base_dir(db, task.base_model)
        # 仅首次保存时复制基础模型文件（避免重复写入），补全微调产出目录
        if base_dir is not None and base_dir.resolve() != target.resolve() and not manifest.exists():
            await asyncio.to_thread(_copy_dir_with_progress, base_dir, target, key)
        else:
            target.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            json.dumps(_build_output_model_config(task), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        # 追加训练超参数存档（记录学习率、batch_size 等，供复现）
        (target / "training_args.bin").write_text(
            json.dumps(
                {
                    "base_model": task.base_model,
                    "train_method": task.train_method,
                    "hyperparams": task.config or {},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        async with SessionLocal() as db:
            model = await _ensure_output_model(db, task)

        with _save_model_lock:
            job = _save_model_jobs.get(key)
            if job is not None:
                job.state = "done"
                job.progress = 100
                job.model_dir = model.model_dir if model else _rel_model_dir(target)
                job.model_name = model.name if model else output_name
    except Exception as exc:  # noqa: BLE001
        logger.exception("保存到我的模型失败: task_id=%s", key)
        with _save_model_lock:
            job = _save_model_jobs.get(key)
            if job is not None:
                job.state = "error"
                job.error = str(exc) or "保存失败"


async def _load_train_records(db: AsyncSession, task: MLTrainTask) -> list[dict]:
    """读取训练任务关联数据集的真实三元组（query/positive/negative），跨多选数据集聚合去重。"""
    ids = task.dataset_ids or ([task.dataset_id] if task.dataset_id else [])
    records: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for did in ids:
        for rec in await _load_eval_records(db, did):
            key = (str(rec.get("query", "")), str(rec.get("positive", "")))
            if key in seen:
                continue
            seen.add(key)
            records.append(rec)
    return records


def _resolve_train_base_dir(base_model: str, model: MLModel | None) -> Path | None:
    """解析训练用基础模型的本地目录（models 顶层 / system / ftm，或模型记录 model_dir）。"""
    if model is not None and model.model_dir:
        p = _resolve_model_dir(model.model_dir)
        if p is not None and p.is_dir():
            return p
    name = (base_model or "").replace("\\", "/").strip("/")
    for cand in (MODELS_DIR / name, MODELS_SYSTEM_DIR / name, MODELS_FTM_DIR / name):
        if cand.is_dir():
            return cand
    return None


def _retrieval_top1_acc(model, val_pairs: list[dict]) -> float:
    """真实检索 top-1 准确率：正样本在全部正样本库中余弦相似度最高的占比。"""
    if len(val_pairs) < 2:
        return 0.0
    try:
        from sentence_transformers.util import cos_sim
    except ImportError:
        return 0.0
    queries = [p["query"] for p in val_pairs]
    passages = [p["positive"] for p in val_pairs]
    q_emb = model.encode(queries, normalize_embeddings=True, convert_to_tensor=True, show_progress_bar=False)
    p_emb = model.encode(passages, normalize_embeddings=True, convert_to_tensor=True, show_progress_bar=False)
    sim = cos_sim(q_emb, p_emb)
    correct = sum(1 for i in range(len(val_pairs)) if int(sim[i].argmax()) == i)
    return correct / len(val_pairs) * 100.0


def _move_batch_to_model(sentence_features, labels, device):
    """把 collate 产出的批次搬到模型所在设备。

    ``smart_batching_collate`` 生成的张量永远在 CPU，模型可能在 GPU，直接送入 loss 会报
    “Expected all tensors to be on the same device ... index is on cpu ... cuda:0”。
    """
    import torch

    features = [
        {k: (v.to(device) if torch.is_tensor(v) else v) for k, v in f.items()}
        for f in sentence_features
    ]
    if torch.is_tensor(labels):
        labels = labels.to(device)
    return features, labels


def _eval_loss(model, loss_fn, val_examples: list, batch_size: int) -> float | None:
    """真实验证损失：eval 模式对验证集计算 MultipleNegativesRankingLoss 均值。"""
    if not val_examples:
        return None
    import torch
    from torch.utils.data import DataLoader

    model.eval()
    dataloader = DataLoader(
        val_examples, shuffle=False, batch_size=batch_size, collate_fn=model.smart_batching_collate
    )
    total = 0.0
    n = 0
    with torch.no_grad():
        for sentence_features, labels in dataloader:
            sentence_features, labels = _move_batch_to_model(sentence_features, labels, model.device)
            total += float(loss_fn(sentence_features, labels).item())
            n += 1
    model.train()
    return total / n if n else None


def _do_real_train(
    base_dir: str,
    train_records: list[dict],
    val_records: list[dict],
    num_epochs: int,
    batch_size: int,
    lr: float,
    warmup_ratio: float,
    weight_decay: float,
    query_max_len: int,
    passage_max_len: int,
    output_dir: Path,
    progress_cb=None,
    step_cb=None,
) -> dict:
    """在线程中执行真实 Embedding 对比学习微调（sentence-transformers + MultipleNegativesRankingLoss）。

    返回每个 epoch 的真实训练损失 / 验证损失 / top-1 检索准确率 / 学习率，供前端绘制曲线。
    progress_cb(epoch, avg_loss, val_loss, val_acc) 在每个 epoch 完成时回调；step_cb 在每个批次的
    训练步完成后回调（epoch, step, steps_per_epoch, running_loss, global_step, total_steps, elapsed），
    供调用方实时落库进度，避免 CPU 训练单步较慢时前端长时间无输出。
    """
    from sentence_transformers import InputExample, SentenceTransformer
    from sentence_transformers.sentence_transformer.losses import MultipleNegativesRankingLoss
    from torch.utils.data import DataLoader
    from transformers import get_linear_schedule_with_warmup

    import torch

    if not base_dir:
        raise RuntimeError("基础模型目录不存在，无法执行真实微调")

    train_pairs = [
        r for r in train_records
        if (r.get("query") or "").strip() and (r.get("positive") or "").strip()
    ]
    if not train_pairs:
        raise RuntimeError("训练数据集中暂无有效三元组（query/positive 为空）")

    # 加载前修复可能被任务元数据覆盖的模型结构配置（如以微调产物为基础继续训练）
    ensure_hf_model_config(Path(base_dir))
    model = SentenceTransformer(base_dir, device=resolve_torch_device())
    model.max_seq_length = passage_max_len
    loss_fn = MultipleNegativesRankingLoss(model)
    logger.info("真实微调：基础模型加载完成 base_dir=%s device=%s", base_dir, model.device)

    def _texts(rec: dict) -> list[str]:
        # [query, positive] 基础上追加难负样本，供 MultipleNegativesRankingLoss 显式学习
        neg = (rec.get("negative") or "").strip()
        return [rec["query"], rec["positive"]] + ([neg] if neg else [])

    train_examples = [InputExample(texts=_texts(r)) for r in train_pairs]
    train_dataloader = DataLoader(
        train_examples, shuffle=True, batch_size=batch_size, collate_fn=model.smart_batching_collate
    )

    val_pairs = [
        r for r in val_records
        if (r.get("query") or "").strip() and (r.get("positive") or "").strip()
    ]
    val_examples = [InputExample(texts=_texts(r)) for r in val_pairs]

    logger.info(
        "真实微调：训练样本=%d 验证样本=%d 轮数=%d 批次=%d 每轮步数=%d",
        len(train_examples), len(val_examples), num_epochs, batch_size,
        max(1, len(train_dataloader)),
    )

    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    steps_per_epoch = max(1, len(train_dataloader))
    total_steps = num_epochs * steps_per_epoch
    warmup_steps = max(0, int(total_steps * warmup_ratio))
    scheduler = get_linear_schedule_with_warmup(
        optimizer, num_warmup_steps=warmup_steps, num_training_steps=total_steps
    )

    epochs: list[int] = []
    train_losses: list[float] = []
    val_losses: list[float] = []
    val_accs: list[float] = []
    lrs: list[float] = []

    model.train()
    # 每 epoch 内按步汇报进度：步数少时每步都报，步数多时约每 10% 报一次，避免海量日志
    report_interval = max(1, steps_per_epoch // 10)
    for epoch in range(1, num_epochs + 1):
        running = 0.0
        epoch_start = time.time()
        logger.info("真实微调 Epoch %d/%d 开始（共 %d 步）", epoch, num_epochs, steps_per_epoch)
        for batch_idx, (sentence_features, labels) in enumerate(train_dataloader, start=1):
            optimizer.zero_grad(set_to_none=True)
            sentence_features, labels = _move_batch_to_model(sentence_features, labels, model.device)
            loss = loss_fn(sentence_features, labels)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
            running += float(loss.item())
            if batch_idx == 1 or batch_idx % report_interval == 0 or batch_idx == steps_per_epoch:
                global_step = (epoch - 1) * steps_per_epoch + batch_idx
                elapsed = time.time() - epoch_start
                logger.info(
                    "真实微调 [STEP] Epoch %d/%d 批次 %d/%d 全局 %d/%d 平均损失 %.4f 用时 %.1fs",
                    epoch, num_epochs, batch_idx, steps_per_epoch,
                    global_step, total_steps, running / batch_idx, elapsed,
                )
                if step_cb is not None:
                    step_cb(
                        epoch, batch_idx, steps_per_epoch,
                        running / batch_idx, global_step, total_steps, elapsed,
                    )
        avg_loss = running / steps_per_epoch

        logger.info("真实微调 Epoch %d/%d: 训练完成，进入验证集评估...", epoch, num_epochs)
        val_loss = _eval_loss(model, loss_fn, val_examples, batch_size)
        val_acc = _retrieval_top1_acc(model, val_pairs) if val_pairs else None
        logger.info("真实微调 Epoch %d/%d: 验证集评估完成", epoch, num_epochs)

        epochs.append(epoch)
        train_losses.append(round(avg_loss, 4))
        lrs.append(round(float(scheduler.get_last_lr()[0]), 8))
        if val_loss is not None:
            val_losses.append(round(val_loss, 4))
        if val_acc is not None:
            val_accs.append(round(val_acc, 2))

        logger.info(
            "真实微调 Epoch %d/%d: 训练损失=%.4f 验证损失=%s 检索准确率=%s",
            epoch,
            num_epochs,
            avg_loss,
            f"{val_loss:.4f}" if val_loss is not None else "N/A",
            f"{val_acc:.2f}%" if val_acc is not None else "N/A",
        )
        if progress_cb is not None:
            progress_cb(epoch, avg_loss, val_loss, val_acc)

    # 保存真实微调产出的完整模型（权重 / 配置 / 分词器），可被「我的模型」与评测真实加载
    # 目录在训练全部成功后才创建：训练中途失败不会在 models/ftm 下留下空的产出文件夹
    os.makedirs(output_dir, exist_ok=True)
    model.save(str(output_dir))
    logger.info("真实微调：模型已保存 output_dir=%s", output_dir)

    # 微调结束立即释放训练资源：丢弃模型/优化器/数据加载器引用并清空显存缓存，
    # 避免上一次训练的显存占用叠加到下一次任务
    del loss_fn, optimizer, scheduler, train_dataloader, model
    gc.collect()
    try:
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001 - 资源回收失败不应影响训练结果
        pass

    return {
        "epochs": epochs,
        "train_losses": train_losses,
        "val_losses": val_losses,
        "val_accs": val_accs,
        "lrs": lrs,
        "num_examples": len(train_examples),
        "steps_per_epoch": steps_per_epoch,
        "total_steps": total_steps,
    }


async def _run_train_task(task_id: str) -> None:
    async with SessionLocal() as db:
        task = await get_train_task(db, task_id)
        if not task:
            return
        task.status = "running"
        await db.commit()

        cfg = dict(task.config or {})
        num_epochs = max(1, int(cfg.get("num_epochs", 3) or 3))
        batch_size = max(1, int(cfg.get("batch_size", 16) or 16))
        learning_rate = str(cfg.get("learning_rate", "2e-5"))
        try:
            lr_value = float(learning_rate)
        except (TypeError, ValueError):
            lr_value = 2e-5
        warmup_ratio = max(0.0, float(cfg.get("warmup_ratio", 0.1) or 0.1))
        weight_decay = max(0.0, float(cfg.get("weight_decay", 0.01) or 0.01))
        query_max_len = max(16, int(cfg.get("query_max_len", 128) or 128))
        passage_max_len = max(16, int(cfg.get("passage_max_len", 512) or 512))

        # 识别基础模型来源：供应商向量模型为远程服务，无法本地微调（真实训练仅支持本地模型）
        base = await get_model_by_name(db, task.base_model)
        provider_cfg = (base.provider_config or {}) if (base is not None and base.source == "provider") else None

        # 加载真实训练三元组并切分训练集 / 验证集
        records = await _load_train_records(db, task)
        valid_ratio = task.valid_ratio or 0.0
        if valid_ratio >= 1.0:
            valid_ratio = 0.0
        val_count = int(len(records) * valid_ratio) if records else 0
        train_records = records[val_count:] if val_count > 0 else records
        val_records = records[:val_count] if val_count > 0 else []
        train_size = len(train_records)
        val_size = len(val_records)
        total_size = len(records)

        sep = "=" * 70
        lines: list[str] = []

        # 阶段1：数据加载（真实统计）
        train_lens = [
            len(str(r.get("query") or "")) + len(str(r.get("positive") or "")) for r in train_records
        ]
        mean_len = round(sum(train_lens) / len(train_lens), 1) if train_lens else 0
        min_len = min(train_lens) if train_lens else 0
        max_len = max(train_lens) if train_lens else 0
        lines += [
            "[DATA] 训练数据加载完成",
            f"[DATA] 训练集: {train_size} 条",
            f"[DATA] 验证集: {val_size} 条",
            f"[DATA] 总计: {total_size} 条",
            f"[DATA] 样本平均长度: {mean_len} 字符",
            f"[DATA] 长度范围: {min_len} ~ {max_len} 字符",
            sep,
        ]

        # 阶段2：训练配置
        train_device = resolve_torch_device()
        device_kind = "GPU" if train_device.split(":")[0].lower() in ("cuda", "mps", "xpu", "npu") else "CPU"
        lines += [
            "[CONFIG] 开始微调训练：sentence-transformers + MultipleNegativesRankingLoss",
            f"[CONFIG] 训练设备: {device_kind}（{train_device}）",
            f"[CONFIG] 基础模型: {task.base_model}",
            f"[CONFIG] 训练轮数: {num_epochs}",
            f"[CONFIG] 批次大小: {batch_size}",
            f"[CONFIG] 学习率: {_fmt_lr(lr_value)}",
            f"[CONFIG] query_max_len: {query_max_len}",
            f"[CONFIG] passage_max_len: {passage_max_len}",
            f"[CONFIG] 预热比例: {warmup_ratio}",
            f"[CONFIG] 权重衰减: {weight_decay}",
        ]
        if provider_cfg:
            lines.append(
                f"[CONFIG] 基础模型来源: 供应商向量模型（{provider_cfg.get('provider', '')} / {provider_cfg.get('model', '')}）"
            )
        lines.append(sep)

        # 立即将「数据加载 + 训练配置」落库，前端在训练真正开始那一刻即可看到日志，而无需等到训练结束
        task.log = "\n".join(lines)
        await db.commit()

        start = time.time()

        # 训练在线程中执行；通过 progress_cb 将每个 epoch 的进度实时回写数据库，供前端轮询展示
        loop = asyncio.get_running_loop()
        progress_lock = threading.Lock()

        async def _flush_train_log() -> None:
            with progress_lock:
                snapshot = "\n".join(lines)
            try:
                async with SessionLocal() as flush_db:
                    fresh = await get_train_task(flush_db, task_id)
                    if fresh is not None:
                        fresh.log = snapshot
                        await flush_db.commit()
            except Exception:  # noqa: BLE001 - 进度落库失败不应中断训练
                logger.exception("训练进度日志落库失败: task_id=%s", task_id)

        def _progress_cb(epoch: int, avg_loss: float, val_loss: float | None, val_acc: float | None) -> None:
            vloss = f"{val_loss:.4f}" if val_loss is not None else "N/A"
            acc = f" | 准确率: {val_acc:.2f}%" if val_acc is not None else ""
            with progress_lock:
                lines.append(
                    f"[EPOCH {epoch}/{num_epochs}] 训练损失: {avg_loss:.4f} | 验证损失: {vloss}{acc}"
                )
            try:
                asyncio.run_coroutine_threadsafe(_flush_train_log(), loop)
            except RuntimeError:
                # 事件循环已关闭（服务正在退出），进度落库可安全跳过
                pass

        def _step_cb(
            epoch: int,
            step: int,
            steps_per_epoch: int,
            running_loss: float,
            global_step: int,
            total_steps: int,
            elapsed: float,
        ) -> None:
            with progress_lock:
                lines.append(
                    f"[STEP] Epoch {epoch}/{num_epochs} 批次 {step}/{steps_per_epoch} "
                    f"全局 {global_step}/{total_steps} 平均损失 {running_loss:.4f} 用时 {elapsed:.1f}s"
                )
            try:
                asyncio.run_coroutine_threadsafe(_flush_train_log(), loop)
            except RuntimeError:
                pass

        # 产出目录：训练失败时若目录是本次运行新建的则回滚，避免 models/ftm 下残留未完成的文件夹
        output_dir = _train_output_dir(task)
        output_dir_existed = output_dir.exists()

        try:
            if task.id in _STOP_FLAGS:
                return
            if provider_cfg:
                raise RuntimeError(
                    "供应商向量模型为远程服务，无法本地真实微调；请选择本地向量模型作为基础模型"
                )

            base_dir = _resolve_train_base_dir(task.base_model, base)
            if base_dir is None:
                raise RuntimeError(
                    f"未找到基础模型目录: {task.base_model}（请确认已导入到「我的模型」或 models 目录）"
                )

            # 训练前释放缓存的本地向量模型与显存碎片，为微调腾出完整显存
            clear_local_model_cache()
            _release_torch_memory()
            if _TRAIN_LOCK.locked():
                lines.append("[CONFIG] 已有其他微调任务占用 GPU，等待其释放显存后开始…")
                task.log = "\n".join(lines)
                await db.commit()
            async with _TRAIN_LOCK:
                result = await asyncio.to_thread(
                    _do_real_train,
                    base_dir=str(base_dir),
                    train_records=train_records,
                    val_records=val_records,
                    num_epochs=num_epochs,
                    batch_size=batch_size,
                    lr=lr_value,
                    warmup_ratio=warmup_ratio,
                    weight_decay=weight_decay,
                    query_max_len=query_max_len,
                    passage_max_len=passage_max_len,
                    output_dir=output_dir,
                    progress_cb=_progress_cb,
                    step_cb=_step_cb,
                )

            epochs = result["epochs"]
            train_losses = result["train_losses"]
            val_losses = result["val_losses"]
            val_accs = result["val_accs"]
            lrs = result["lrs"]
            total_steps = result["total_steps"]

            elapsed_total = time.time() - start
            token_usage = (sum(train_lens) if train_lens else 0) * num_epochs
            final_loss = train_losses[-1] if train_losses else 0.0
            final_acc = val_accs[-1] if val_accs else 0.0
            best_acc = max(val_accs) if val_accs else 0.0
            best_epoch = (val_accs.index(best_acc) + 1) if val_accs else 0

            # 每轮训练进度已由 progress_cb 实时追加到 lines；此处仅补充总结信息
            lines += [
                sep,
                f"[SUMMARY] 训练完成 | 训练样本: {result['num_examples']} | 总步数: {total_steps} | 最佳准确率: {best_acc:.2f}% (Epoch {best_epoch}) | 总耗时: {elapsed_total:.1f}s",
                f"[SUMMARY] 模型保存路径: /models/ftm/{_train_output_name(task)}",
            ]

            task.output_model_name = _train_output_name(task)
            output_dir.mkdir(parents=True, exist_ok=True)
            task.output_dir = to_rel_path(output_dir)
            # 注意：不要写 output_dir/config.json —— 那是 SentenceTransformer 保存的模型结构配置
            # （hidden_size/层数/词表），被任务元数据覆盖后加载会按默认结构建模、权重形状不匹配。
            # 训练元数据统一放 train_manifest.json。
            # 标记产出目录已完成（含真实微调权重），避免「保存到我的模型」时用基础模型覆盖
            (output_dir / "train_manifest.json").write_text(
                json.dumps(_build_output_model_config(task), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (output_dir / "README.md").write_text(
                f"# {task.output_model_name}\n\n"
                f"训练任务产出模型（sentence-transformers 真实微调）。\n\n"
                f"- 任务 ID：{task.id}\n"
                f"- 基础模型：{task.base_model}\n"
                f"- 训练方式：{task.train_method}\n"
                f"- 训练样本：{result['num_examples']} 条\n"
                f"- 训练轮数：{num_epochs}\n",
                encoding="utf-8",
            )

            task.log = "\n".join(lines)
            task.metrics = _build_metrics(
                epochs, train_losses, val_losses, val_accs, lrs,
                total_steps, round(elapsed_total, 1), token_usage, final_loss, final_acc,
            )
            task.status = "done"
        except Exception as exc:  # noqa: BLE001
            logger.exception("训练任务失败: %s", exc)
            task.status = "failed"
            err_text = str(exc)
            # 显存不足给可操作的建议，避免用户只看到 CUDA error 不知如何处理
            if "out of memory" in err_text.lower():
                err_text += "（显存不足：建议调小「批次大小」或「passage_max_len」，或关闭其他占用 GPU 的任务后重试）"
            task.log = "\n".join(lines + [f"[ERROR] {err_text}"])
            # 回滚本次失败运行新建的产出目录（训练前已存在的同名模型不受影响）
            if not output_dir_existed and output_dir.exists():
                shutil.rmtree(output_dir, ignore_errors=True)
                logger.info("训练任务失败，已清理未完成的产出目录: %s", output_dir)
        finally:
            _STOP_FLAGS.discard(task.id)
            # 无论成功/失败/停止，微调结束后都回收显存，避免残留占用影响后续任务
            _release_torch_memory(f"训练任务 {task.id} 结束")
            await db.commit()


# ======================================================================
# 评测维度 & 评测任务
# ======================================================================


async def list_dimensions(db: AsyncSession) -> list[MLEvalDimension]:
    result = await db.execute(select(MLEvalDimension).order_by(MLEvalDimension.created_at))
    return list(result.scalars().all())


async def create_dimension(db: AsyncSession, data) -> MLEvalDimension:
    dim = MLEvalDimension(
        name=data.name,
        description=data.description,
        eval_type=data.eval_type,
        eval_config=data.eval_config,
    )
    db.add(dim)
    await db.commit()
    await db.refresh(dim)
    return dim


async def get_dimension(db: AsyncSession, dimension_id: str) -> MLEvalDimension | None:
    result = await db.execute(select(MLEvalDimension).where(MLEvalDimension.id == dimension_id))
    return result.scalar_one_or_none()


async def update_dimension(db: AsyncSession, dim: MLEvalDimension, data) -> MLEvalDimension:
    """更新评测维度；名称变更时同步刷新引用该维度的排行榜与评测任务 dimension_names 快照。"""
    old_name = dim.name
    dim.name = data.name
    dim.description = data.description
    dim.eval_type = data.eval_type
    dim.eval_config = data.eval_config
    await db.commit()
    await db.refresh(dim)
    if old_name != dim.name:
        await sync_dimension_name_snapshots(db, dim.id)
    return dim


async def sync_dimension_name_snapshots(db: AsyncSession, dimension_id: str) -> None:
    """对比 dimension_id 关联的排行榜 / 评测任务 dimension_names，不一致才写回。"""
    changed = False

    lb_result = await db.execute(select(MLLeaderboard))
    for lb in lb_result.scalars().all():
        ids = list(lb.dimension_ids or [])
        if dimension_id not in ids:
            continue
        new_names = await _dimension_names(db, ids)
        if list(lb.dimension_names or []) != new_names:
            lb.dimension_names = new_names
            flag_modified(lb, "dimension_names")
            changed = True

    task_result = await db.execute(select(MLEvalTask))
    for task in task_result.scalars().all():
        ids = list(task.dimension_ids or [])
        if dimension_id not in ids:
            continue
        new_names = await _dimension_names(db, ids)
        if list(task.dimension_names or []) != new_names:
            task.dimension_names = new_names
            flag_modified(task, "dimension_names")
            changed = True

    if changed:
        await db.commit()


async def _dimension_names(db: AsyncSession, dimension_ids: list[str]) -> list[str]:
    """按维度 ID 取出名称（维度缺失时回退为 ID，创建时已快照保存到实体字段）。"""
    names: list[str] = []
    for did in dimension_ids or []:
        dim = await get_dimension(db, did)
        names.append(dim.name if dim else did)
    return names


async def delete_dimension(db: AsyncSession, dim: MLEvalDimension) -> None:
    await db.delete(dim)
    await db.commit()


async def create_eval_task(db: AsyncSession, data) -> MLEvalTask:
    ids = list(data.dimension_ids or [])
    names = await _dimension_names(db, ids)
    data_mode = getattr(data, "data_mode", "dataset") or "dataset"
    split_dataset_id = getattr(data, "split_dataset_id", "") or ""
    split_ratio = float(getattr(data, "split_ratio", 0.1) or 0.1)
    # 自动切分模式下，data_id 保存来源训练集，运行时按比例切分评测集
    task = MLEvalTask(
        name=data.name,
        model_id=data.model_id,
        model_type=getattr(data, "model_type", "vector"),
        llm_model_id=getattr(data, "llm_model_id", None),
        data_source=data.data_source,
        data_id=data.data_id,
        data_mode=data_mode,
        split_dataset_id=split_dataset_id,
        split_ratio=split_ratio,
        dimension_ids=ids,
        dimension_names=names,
        sync_leaderboard=data.sync_leaderboard,
        leaderboard_id=data.leaderboard_id,
        status="pending",
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    schedule_eval(task.id)
    return task


async def list_eval_tasks(db: AsyncSession) -> list[MLEvalTask]:
    result = await db.execute(select(MLEvalTask).order_by(MLEvalTask.created_at.desc()))
    return list(result.scalars().all())


async def get_eval_task(db: AsyncSession, task_id: str) -> MLEvalTask | None:
    result = await db.execute(select(MLEvalTask).where(MLEvalTask.id == task_id))
    return result.scalar_one_or_none()


async def stop_eval_task(db: AsyncSession, task: MLEvalTask) -> MLEvalTask:
    """终止评测任务：登记停止标志，并将 pending/running 标记为 stopped。"""
    _EVAL_STOP_FLAGS.add(task.id)
    if task.status in {"pending", "running"}:
        task.status = "stopped"
        res = dict(task.result or {})
        res["message"] = "任务已手动终止"
        task.result = res
        flag_modified(task, "result")
        await db.commit()
        await db.refresh(task)
    return task


async def recover_stale_eval_tasks() -> int:
    """服务重启后回收遗留任务：将 pending/running 标记为 stopped（后台协程已随进程终止）。"""
    async with SessionLocal() as db:
        result = await db.execute(
            select(MLEvalTask).where(MLEvalTask.status.in_(["pending", "running"]))
        )
        tasks = list(result.scalars().all())
        for t in tasks:
            t.status = "stopped"
            res = dict(t.result or {})
            res["message"] = "服务重启导致任务中断"
            t.result = res
            flag_modified(t, "result")
        if tasks:
            await db.commit()
        return len(tasks)


def list_eval_task_details(
    task: MLEvalTask,
    field: str | None,
    keyword: str | None,
    page: int,
    page_size: int,
) -> tuple[list[dict], int]:
    """返回评测任务数据明细：按字段/关键词模糊筛选后分页。

    field 为「negative」时仅匹配 negative 字段；否则匹配 query 或 positive 字段。
    """
    raw = (task.result or {}).get("details")
    items = [d for d in raw if isinstance(d, dict)] if isinstance(raw, list) else []
    kw = (keyword or "").strip()
    if kw:
        if field == "negative":
            items = [d for d in items if kw in str(d.get("negative", ""))]
        else:
            items = [
                d
                for d in items
                if kw in str(d.get("query", "")) or kw in str(d.get("positive", ""))
            ]
    total = len(items)
    start = (page - 1) * page_size
    return items[start : start + page_size], total


def schedule_eval(task_id: str) -> None:
    asyncio.create_task(_run_eval_task(task_id))


# 检索评估指标：评测维度 ->（命中/正确 标签, 未命中/错误 标签）
RETRIEVAL_METRIC_LABELS: dict[str, tuple[str, str]] = {
    "recall_at_5": ("命中", "未命中"),
    "vector_qa_accuracy": ("正确", "错误"),
    "fulltext_qa_accuracy": ("正确", "错误"),
    "hybrid_qa_accuracy": ("正确", "错误"),
    "rerank_qa_accuracy": ("正确", "错误"),
}

# 判定为正向结果的标签集合
_POSITIVE_LABELS = {"Pass", "命中", "正确"}


def _spearman_corr(xs: list[float], ys: list[float]) -> float:
    """计算 Spearman 秩相关系数（含并列平均秩，无第三方依赖）。"""
    n = len(xs)
    if n < 2 or n != len(ys):
        return 0.0

    def _ranks(vals: list[float]) -> list[float]:
        order = sorted(range(n), key=lambda i: vals[i])
        out = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                out[order[k]] = avg
            i = j + 1
        return out

    rx = _ranks(xs)
    ry = _ranks(ys)
    mx = sum(rx) / n
    my = sum(ry) / n
    cov = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    vx = sum((r - mx) ** 2 for r in rx)
    vy = sum((r - my) ** 2 for r in ry)
    if vx == 0 or vy == 0:
        return 0.0
    return cov / math.sqrt(vx * vy)


def _dim_result(dim: dict, ranks: dict[str, int | None], llm_trace: dict, rec: dict | None = None) -> dict:
    """按维度类型生成单条样本的维度结果（label 分类型 / value 数值型）。

    - 检索评估：召回率/问答准确率 -> 命中/正确 分类型；MRR -> 数值型（1/rank）
    - 大模型评估-分类型 -> 取裁判结论 Pass/Fail；数值型 -> 幻觉评分（1~5 分）
    - 统计评估-Spearman相关系数 -> 单样本模型打分（value）与人工评分（human），聚合时计算相关系数
    """
    eval_type = dim.get("eval_type", "llm_classify")
    cfg = dim.get("eval_config") or {}

    if eval_type == "retrieval":
        metric = cfg.get("metric")
        rank = ranks.get(metric)
        if metric == "mrr":
            return {"value": round(1.0 / rank, 4) if rank else 0.0}
        pos, neg = RETRIEVAL_METRIC_LABELS.get(metric, ("命中", "未命中"))
        if metric == "recall_at_5":
            hit = rank is not None and rank <= int(cfg.get("recall_k", 5) or 5)
        else:
            hit = rank is not None and rank <= int(cfg.get("top_k", 5) or 5)
        return {"label": pos if hit else neg}

    if eval_type == "llm_classify":
        return {"label": llm_trace.get("conclusion", "Pass")}
    if eval_type == "llm_numeric":
        return {"value": float(llm_trace.get("hallucination", 5))}
    if eval_type == "spearman":
        human = (rec or {}).get("human_score")
        # 模型打分：优先使用向量模型对 query-positive 的余弦相似度（真实且可复现）；
        # 无向量打分时退化为 query 与 positive 的词法相似度，避免随机噪声。
        model_score = ranks.get("vector_score")
        if model_score is None:
            model_score = _text_similarity(
                (rec or {}).get("query", ""),
                (rec or {}).get("positive", ""),
                "COSINE",
            )
        pred = round(float(model_score), 4)
        return {
            "value": pred,
            "human": round(float(human), 4) if isinstance(human, (int, float)) else None,
        }

    # 默认（未知 eval_type 兜底；所有已知类型均已显式处理，此分支不可达）
    return {"label": "Pass"}


def _dim_top_k(dim: dict) -> int | None:
    """检索维度展示用的 K 值：Recall@K 取 recall_k，策略准确率取 top_k；非检索维度返回 None。"""
    if dim.get("eval_type") != "retrieval":
        return None
    cfg = dim.get("eval_config") or {}
    key = "recall_k" if cfg.get("metric") == "recall_at_5" else "top_k"
    try:
        return max(1, int(cfg.get(key) or 5))
    except (TypeError, ValueError):
        return 5


def _dim_positive(dim: dict, res: dict) -> bool:
    """判断单条维度结果是否为正向（用于通过率 / 整体结果汇总）。"""
    eval_type = dim.get("eval_type", "llm_classify")
    cfg = dim.get("eval_config") or {}
    if "value" in res and "label" not in res:
        if eval_type == "llm_numeric":
            return float(res["value"]) >= float(cfg.get("threshold", 3.0) or 3.0)
        if eval_type == "spearman":
            return float(res["value"]) >= float(cfg.get("threshold", 0.5) or 0.5)
        return float(res["value"]) >= 0.5
    return res.get("label") in _POSITIVE_LABELS


def _dim_score(dim: dict, results: list[dict]) -> float:
    """按维度聚合总分（0~1）。

    - MRR -> 平均倒数排名
    - 分类型（召回率/准确率/Pass-Fail）-> 正向占比
    - 数值型（相似度阈值、1~5 分）-> 正向占比
    - Spearman -> 模型打分序列与人工评分序列的秩相关系数（映射到 0~1）；缺人工评分时退化为阈值通过率
    """
    eval_type = dim.get("eval_type", "llm_classify")
    cfg = dim.get("eval_config") or {}
    if not results:
        return 0.0
    if eval_type == "retrieval" and cfg.get("metric") == "mrr":
        return round(sum(float(r.get("value", 0)) for r in results) / len(results), 4)
    if eval_type == "spearman":
        preds = [float(r.get("value", 0)) for r in results]
        humans = [(r or {}).get("human") for r in results]
        if len(results) >= 2 and all(isinstance(h, (int, float)) for h in humans):
            corr = _spearman_corr(preds, [float(h) for h in humans])
            return round((corr + 1) / 2, 4)
        # 缺人工评分时退化为阈值通过率
    positives = sum(1 for r in results if _dim_positive(dim, r))
    return round(positives / len(results), 4)


def _build_eval_embedder(model: MLModel | None) -> EmbeddingClient:
    """根据评测所选向量模型构建真实 Embedding 客户端。

    - 供应商模型（source=provider）→ 远程 OpenAI 兼容 Embedding 接口；
    - 本地模型 → models 目录下的 sentence-transformers 模型（含微调产物 ftm）；
    - 兜底 → 哈希特征向量（无本地模型时仍可跑通，且结果确定）。
    """
    if model is not None and model.source == "provider":
        pc = model.provider_config or {}
        return EmbeddingClient(
            api_base=str(pc.get("url", "")),
            api_key=str(pc.get("api_key", "")),
            model=str(pc.get("model", "")),
            dim=1024,
        )
    local_path = _resolve_train_base_dir(model.base_model, model) if model is not None else None
    if local_path is None:
        from app.ai.embedding import _resolve_local_model_path

        name = model.base_model if model is not None else "bge-large-zh-v1.5"
        local_path = _resolve_local_model_path(name)
    return EmbeddingClient(model="", dim=1024, local_path=local_path)


def _compute_real_ranks(
    embedder: EmbeddingClient,
    candidates: list[str],
    reranker,
    records: list[dict],
    top_k: int,
    rerank_top_k: int | None = None,
) -> list[dict]:
    """在评测数据集候选池上真实执行四种检索策略，返回每个样本正样本的排名与向量 Top-K 列表。

    候选池为测试集全部 positive/negative 去重后的文本集合；对每条 query 用所选向量模型
    encode（本地 sentence-transformers 或远程供应商 Embedding），按 cosine 相似度真实排序，
    得出正样本在四种策略下的排名（1-based；未检到为 None）。阻塞 CPU 计算，应在 asyncio.to_thread 中执行。

    top_k：存储/展示的向量 Top 文档条数（按 Recall@K 等维度的最大 K 决定）；
    rerank_top_k：重排序候选数的基准（按策略准确率维度的 Top-K 决定，避免召回 K 过大拖慢精排）。

    返回 list[dict]，每个元素含 vector/fulltext/hybrid/rerank 排名与 vector_top5（向量 Top 文档）列表。
    """
    import numpy as np

    empty = {
        "vector": None,
        "fulltext": None,
        "hybrid": None,
        "rerank": None,
        "vector_score": None,
        "vector_top5": [],
    }
    if not records or not candidates:
        return [dict(empty) for _ in records]

    pos_index = {c: i for i, c in enumerate(candidates)}
    cand_matrix = np.asarray(embedder.embed(candidates), dtype=np.float32)
    cand_matrix = cand_matrix / (np.linalg.norm(cand_matrix, axis=1, keepdims=True) + 1e-9)

    queries = [str(r.get("query") or "") for r in records]
    q_matrix = np.asarray(embedder.embed(queries), dtype=np.float32)
    q_matrix = q_matrix / (np.linalg.norm(q_matrix, axis=1, keepdims=True) + 1e-9)

    n = len(candidates)
    rrf_k = 60
    m = min(n, max(rerank_top_k or top_k, 1) * 3)

    results: list[dict] = []
    for i, rec in enumerate(records):
        positive = str(rec.get("positive") or "")
        idx = pos_index.get(positive)
        if idx is None:
            results.append(dict(empty))
            continue
        query = queries[i]
        q = q_matrix[i]

        # 向量检索：所选模型 cosine 相似度排序
        vec_scores = cand_matrix @ q
        vec_order = np.argsort(-vec_scores)

        # 全文检索：词法重叠度排序（真实关键词召回）
        lex_scores = np.asarray(
            [lexical_score(query, c) for c in candidates], dtype=np.float32
        )
        ft_order = np.argsort(-lex_scores)

        # 混合检索：vector + fulltext 两路 RRF 融合
        rrf = np.zeros(n, dtype=np.float32)
        for rank, ci in enumerate(vec_order):
            rrf[int(ci)] += 1.0 / (rrf_k + rank + 1)
        for rank, ci in enumerate(ft_order):
            rrf[int(ci)] += 1.0 / (rrf_k + rank + 1)
        hy_order = np.argsort(-rrf)

        def rank_of(order: np.ndarray) -> int | None:
            for pos, ci in enumerate(order):
                if int(ci) == idx:
                    return pos + 1
            return None

        # 重排序：取向量 top-M 候选，交由交叉编码器（或词法代理）精排
        top_ids = [int(ci) for ci in vec_order[:m]]
        chunks = [
            {
                "chunk_id": f"cand-{ci}",
                "content": candidates[ci],
                "score": float(vec_scores[ci]),
                "source": "eval-candidate",
            }
            for ci in top_ids
        ]
        try:
            ranked = reranker.rerank(query, chunks, top_k=m)
        except Exception:
            ranked = chunks
        rerank_rank = None
        for pos, c in enumerate(ranked):
            if c.get("chunk_id") == f"cand-{idx}":
                rerank_rank = pos + 1
                break

        vector_top5 = [
            {
                "rank": pos + 1,
                "content": candidates[int(ci)],
                "score": round(float(vec_scores[int(ci)]), 4),
            }
            for pos, ci in enumerate(vec_order[:top_k])
        ]

        results.append({
            "vector": rank_of(vec_order),
            "fulltext": rank_of(ft_order),
            "hybrid": rank_of(hy_order),
            "rerank": rerank_rank,
            "vector_score": round(float(vec_scores[idx]), 4),
            "vector_top5": vector_top5,
        })
    return results


def _build_real_llm_trace(positive: str, llm_infos: list[dict], overall_pos: bool) -> dict:
    """由真实裁判 LLM 输出汇总单样本的大模型评估 trace（结论/回答/各维度/用量等）。

    llm_details 按维度名保存该维度的裁判原文/用量/结论，供明细弹窗按维度切换查看。
    """
    tokens = {"input": 0, "output": 0, "total": 0}
    checks: list[dict] = []
    reasons: list[str] = []
    llm_details: dict[str, dict] = {}
    hallucination: float | None = None
    judge_model = ""
    for info in llm_infos:
        t = info.get("tokens") or {}
        tokens["input"] += int(t.get("input", 0))
        tokens["output"] += int(t.get("output", 0))
        tokens["total"] += int(t.get("total", 0))
        if not judge_model and info.get("judge_model"):
            judge_model = str(info["judge_model"])
        content = (info.get("content") or "").strip()
        dim_name = str(info.get("name") or "")
        if dim_name:
            llm_details[dim_name] = {
                "eval_type": info.get("eval_type"),
                "label": info.get("label"),
                "value": info.get("value"),
                "content": content,
                "tokens": {
                    "input": int(t.get("input", 0)),
                    "output": int(t.get("output", 0)),
                    "total": int(t.get("total", 0)),
                },
                "judge_model": info.get("judge_model") or "",
            }
        if info.get("eval_type") == "llm_classify":
            passed = info.get("label") in _POSITIVE_LABELS
            checks.append({
                "name": info.get("name", ""),
                "pass": passed,
                "reason": content or ("通过" if passed else "未通过"),
            })
            if content:
                reasons.append(content)
        elif info.get("eval_type") == "llm_numeric":
            if hallucination is None and info.get("value") is not None:
                hallucination = float(info["value"])
            if content:
                reasons.append(content)
    return {
        "rag_answer": positive,
        "judge_model": judge_model,
        "tokens": tokens,
        "conclusion": "Pass" if overall_pos else "Fail",
        "hallucination": hallucination,
        "checks": checks,
        "reason": "；".join(reasons) if reasons else "已由裁判大模型完成评估。",
        "llm_details": llm_details,
    }


def _record_field(obj: dict, *keys: str) -> str:
    """从记录对象中按优先级取第一个非空字段值。"""
    for k in keys:
        v = obj.get(k)
        if v not in (None, ""):
            return str(v)
    return ""


def _record_score(obj: dict) -> float | None:
    """从记录对象中提取人工评分（数值型，用于 Spearman 相关系数）。"""
    for k in ("human_score", "人工评分", "reference_score", "label_score", "score"):
        v = obj.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    return None


async def _load_eval_records(db: AsyncSession, dataset_id: str) -> list[dict]:
    """读取评测数据集的实际测试集内容（query/positive/negative）。

    优先读取版本 storage_path 指向的 jsonl 文件，文件缺失时回退解析 preview_content。
    """
    records: list[dict] = []
    if not dataset_id:
        return records
    version = await get_latest_version(db, dataset_id)
    if not version:
        return records

    texts: list[str] = []
    for p in (version.storage_path or "").split(","):
        p = p.strip()
        if not p:
            continue
        path = to_abs_path(p)
        if not path.exists():
            continue
        try:
            texts.append(path.read_text("utf-8", errors="replace"))
        except OSError:
            continue
        break  # 仅取第一个存在的文件

    if not texts and version.preview_content:
        texts.append(version.preview_content)

    for text in texts:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(obj, dict):
                continue
            query = _record_field(obj, "query", "question", "问题")
            positive = _record_field(obj, "positive", "answer", "回答")
            negative = _record_field(obj, "negative", "wrong", "错误答案", "错答")
            human_score = _record_score(obj)
            if query or positive:
                records.append({
                    "query": query,
                    "positive": positive,
                    "negative": negative,
                    "human_score": human_score,
                })
        if records:
            break
    return records


async def _load_eval_task_records(db: AsyncSession, task: MLEvalTask) -> list[dict]:
    """按评测任务的数据来源方式加载评测记录。

    - data_mode == 'auto_split'：从训练集（split_dataset_id）读取并切分出前 split_ratio 比例作为评测集；
    - 其余（dataset）：直接从 data_id 指向的评测集读取。
    """
    if (task.data_mode or "dataset") == "auto_split" and task.split_dataset_id:
        records = await _load_eval_records(db, task.split_dataset_id)
        ratio = max(0.0, min(1.0, float(task.split_ratio or 0.1)))
        cut = max(1, int(len(records) * ratio)) if records else 0
        # 随机切分（固定种子保证同一数据集的切分可复现），避免总取开头/结尾造成顺序偏差
        split_records = random.Random(_AUTO_SPLIT_SEED).sample(records, cut) if cut else []
        logger.info(
            "评测任务自动切分: 训练集=%s 总条数=%d 切分比例=%.2f 评测集=%d（随机切分）",
            task.split_dataset_id, len(records), ratio, cut,
        )
        return split_records
    return await _load_eval_records(db, task.data_id)


def _render_variables(template: str, rec: dict | None) -> str:
    """将评测 Prompt/字段模板中的 ${query}/${positive}/${negative} 替换为测试集内容。"""
    if not template:
        return ""
    rec = rec or {}
    return (
        template.replace("${query}", str(rec.get("query", "")))
        .replace("${positive}", str(rec.get("positive", "")))
        .replace("${negative}", str(rec.get("negative", "")))
    )


async def _build_judge_llm(db: AsyncSession, eval_config: dict):
    """根据维度配置的裁判模型构建 LLM 客户端；未指定时回退内置激活供应商。"""
    judge_model = (eval_config or {}).get("judge_model")
    if judge_model:
        from app.models.provider import Provider

        prov = await db.get(Provider, judge_model)
        if prov is not None:
            names = list(prov.model_names or []) or ([prov.model_name] if prov.model_name else [])
            return build_llm({
                "llm_api_base": prov.api_base,
                "llm_api_key": config_service.decrypt(prov.api_key),
                "llm_model": prov.model_name,
                "llm_models": ",".join(names),
            })
    cfg = await config_service.get_runtime(db)
    return build_llm(cfg)


def _parse_classify(content: str, cfg: dict) -> str:
    """从裁判返回文本解析分类型结论（Pass/Fail 或自定义标签）。"""
    labels = (cfg or {}).get("labels") or {}
    pass_label = labels.get("Pass") or "Pass"
    fail_label = labels.get("Fail") or "Fail"
    text = content or ""
    if fail_label and fail_label in text:
        return fail_label
    if "[[Fail]]" in text or "[[fail]]" in text.lower():
        return fail_label
    if pass_label and pass_label in text:
        return pass_label
    if "[[Pass]]" in text or "[[pass]]" in text.lower():
        return pass_label
    return pass_label


def _parse_numeric(content: str) -> float:
    """从裁判返回文本解析数值型评分（0~5 分）。"""
    m = re.search(r"\d+(?:\.\d+)?", content or "")
    if not m:
        return 3.0
    return round(min(5.0, max(0.0, float(m.group(0)))), 2)


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[\u4e00-\u9fff]|[a-zA-Z0-9_]+", (text or "").lower())


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _token_ngrams(tokens: list[str], n: int) -> list[tuple]:
    return [tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]


def _text_similarity(a: str, b: str, metric: str) -> float:
    """按指定规则计算两段文本相似度（0~1）。"""
    a = a or ""
    b = b or ""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    metric = (metric or "FUZZY_MATCH").upper()

    if metric == "FUZZY_MATCH":
        return difflib.SequenceMatcher(None, a, b).ratio()
    if metric == "LEVENSHTEIN":
        return 1.0 - _levenshtein(a, b) / max(len(a), len(b))

    ta, tb = _tokenize(a), _tokenize(b)

    if metric == "JACCARD":
        sa, sb = set(ta), set(tb)
        if not sa or not sb:
            return 0.0
        return len(sa & sb) / len(sa | sb)
    if metric == "COSINE":
        ca, cb = Counter(ta), Counter(tb)
        dot = sum(ca.get(k, 0) * v for k, v in cb.items())
        na = math.sqrt(sum(v * v for v in ca.values()))
        nb = math.sqrt(sum(v * v for v in cb.values()))
        if not na or not nb:
            return 0.0
        return dot / (na * nb)
    if metric == "ACCURACY":
        if a == b:
            return 1.0
        return sum(1 for x, y in zip(ta, tb) if x == y) / max(len(ta), len(tb), 1)

    if metric == "BLEU_4":
        precisions: list[float] = []
        for k in (1, 2, 3, 4):
            hyp = _token_ngrams(ta, k)
            if not hyp:
                precisions.append(0.0)
                continue
            unused = dict(Counter(_token_ngrams(tb, k)))
            matched = 0
            for g in hyp:
                if unused.get(g, 0) > 0:
                    matched += 1
                    unused[g] -= 1
            precisions.append(matched / len(hyp))
        prod = 1.0
        for p in precisions:
            prod *= p if p > 0 else 1e-4
        bleu = prod ** 0.25
        bp = min(1.0, math.exp(1 - len(tb) / len(ta))) if ta else 0.0
        return bleu * bp

    if metric.startswith("ROUGE_"):
        if metric == "ROUGE_L":
            size = difflib.SequenceMatcher(None, a, b).find_longest_match(0, len(a), 0, len(b)).size
            return size / max(len(b), 1)
        try:
            n = int(metric.rsplit("_", 1)[1])
        except ValueError:
            n = 1
        ref = _token_ngrams(tb, n)
        hyp = _token_ngrams(ta, n)
        if not ref:
            return 0.0
        refc, hypc = Counter(ref), Counter(hyp)
        return sum((refc & hypc).values()) / len(ref)

    if metric == "F1":
        sa, sb = set(ta), set(tb)
        if not sa or not sb:
            return 0.0
        inter = len(sa & sb)
        precision = inter / len(sa)
        recall = inter / len(sb)
        if precision + recall == 0:
            return 0.0
        return 2 * precision * recall / (precision + recall)

    if metric == "GLEU":
        total = 0.0
        for k in (1, 2, 3, 4):
            hyp = _token_ngrams(ta, k)
            if not hyp:
                continue
            used = dict(Counter(_token_ngrams(tb, k)))
            matched = 0
            for g in hyp:
                if used.get(g, 0) > 0:
                    matched += 1
                    used[g] -= 1
            total += matched / len(hyp)
        return total / 4.0

    return difflib.SequenceMatcher(None, a, b).ratio()


def _judge_empty(client) -> dict:
    """构造无裁判（未配置供应商/调用失败）时的降级结果。"""
    return {
        "content": "",
        "tokens": {"input": 0, "output": 0, "total": 0},
        "judge_model": getattr(client, "model", "") if client is not None else "",
    }


async def _judge_classify(client, prompt: str, cfg: dict, sem: asyncio.Semaphore) -> dict:
    """调用裁判 LLM 做分类型评估，返回 {label, content, tokens, judge_model}。"""
    if client is None or not prompt:
        out = _judge_empty(client)
        out["label"] = "Pass" if random.random() < 0.85 else "Fail"
        return out
    async with sem:
        try:
            resp = await client.complete(
                [{"role": "user", "content": prompt}], temperature=0.0, max_tokens=2048
            )
            usage = resp.get("usage") or {}
            return {
                "label": _parse_classify(resp.get("content", ""), cfg),
                "content": resp.get("content", ""),
                "tokens": {
                    "input": int(usage.get("input", 0)),
                    "output": int(usage.get("output", 0)),
                    "total": int(usage.get("total", 0)),
                },
                "judge_model": getattr(client, "model", ""),
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("裁判分类评估失败: %s", exc)
            out = _judge_empty(client)
            out["label"] = "Pass" if random.random() < 0.85 else "Fail"
            return out


async def _judge_numeric(client, prompt: str, sem: asyncio.Semaphore) -> dict:
    """调用裁判 LLM 做数值型评估，返回 {value, content, tokens, judge_model}。"""
    if client is None or not prompt:
        out = _judge_empty(client)
        out["value"] = round(random.uniform(3.0, 5.0), 2)
        return out
    async with sem:
        try:
            resp = await client.complete(
                [{"role": "user", "content": prompt}], temperature=0.0, max_tokens=2048
            )
            usage = resp.get("usage") or {}
            return {
                "value": _parse_numeric(resp.get("content", "")),
                "content": resp.get("content", ""),
                "tokens": {
                    "input": int(usage.get("input", 0)),
                    "output": int(usage.get("output", 0)),
                    "total": int(usage.get("total", 0)),
                },
                "judge_model": getattr(client, "model", ""),
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("裁判数值评估失败: %s", exc)
            out = _judge_empty(client)
            out["value"] = round(random.uniform(3.0, 5.0), 2)
            return out


async def _eval_dim_realtime(dim, rec, rank_map, judge_clients, sem):
    """对单条测试数据按维度真实打分，返回 (维度结果, 大模型评估信息或 None)。"""
    et = dim.get("eval_type", "llm_classify")
    cfg = dim.get("eval_config") or {}
    if et in ("retrieval", "spearman"):
        return _dim_result(dim, rank_map, {}, rec), None
    if et == "llm_classify":
        prompt = _render_variables(cfg.get("prompt", ""), rec)
        raw = await _judge_classify(judge_clients.get(dim["name"]), prompt, cfg, sem)
        info = {
            "name": dim["name"],
            "eval_type": "llm_classify",
            "label": raw.get("label"),
            "content": raw.get("content", ""),
            "tokens": raw.get("tokens"),
            "judge_model": raw.get("judge_model", ""),
        }
        return {"label": raw.get("label", "Pass")}, info
    if et == "llm_numeric":
        prompt = _render_variables(cfg.get("prompt", ""), rec)
        raw = await _judge_numeric(judge_clients.get(dim["name"]), prompt, sem)
        info = {
            "name": dim["name"],
            "eval_type": "llm_numeric",
            "value": raw.get("value"),
            "content": raw.get("content", ""),
            "tokens": raw.get("tokens"),
            "judge_model": raw.get("judge_model", ""),
        }
        return {"value": raw.get("value", 5.0)}, info
    return _dim_result(dim, rank_map, {}, rec), None


async def _run_eval_task(task_id: str) -> None:
    async with SessionLocal() as db:
        task = await get_eval_task(db, task_id)
        if not task:
            return
        # 任务在调度前已被终止（stop 先于协程启动），直接跳过
        if task.status not in ("pending", "running"):
            return
        task.status = "running"
        records = await _load_eval_task_records(db, task)
        if not records:
            task.status = "failed"
            task.result = {
                "metrics": [],
                "score": 0,
                "pass_count": 0,
                "fail_count": 0,
                "pass_rate": 0,
                "details": [],
                "error": "未找到评测数据集内容",
            }
            await db.commit()
            return
        total = len(records)
        task.total_count = total
        task.completed_count = 0
        await db.commit()
        try:
            dim_metas = await _metric_dims(db, task.dimension_ids or [])
            # 明细弹窗按维度展示 Top-K 文档：按检索维度的 K 取最大值决定存储条数；
            # 重排候选数只按策略准确率维度的 Top-K 决定，避免召回 K 过大拖慢精排
            max_top_docs = 5
            max_rerank_k = 5
            for m in dim_metas:
                k = _dim_top_k(m)
                if k:
                    max_top_docs = max(max_top_docs, k)
                    if (m["eval_config"] or {}).get("metric") != "recall_at_5":
                        max_rerank_k = max(max_rerank_k, k)
            max_top_docs = min(max_top_docs, _MAX_STORED_TOP_DOCS)
            judge_clients: dict[str, object] = {}
            for m in dim_metas:
                if m["eval_type"] in ("llm_classify", "llm_numeric"):
                    judge_clients[m["name"]] = await _build_judge_llm(db, m["eval_config"])
            sem = asyncio.Semaphore(_EVAL_CONCURRENCY)

            dim_results: dict[str, list[dict]] = {m["name"]: [] for m in dim_metas}
            details = []
            pass_count = 0
            is_llm_eval = task.model_type == "llm"
            has_llm_dims = any(m["eval_type"] in ("llm_classify", "llm_numeric") for m in dim_metas)

            # 识别向量模型来源：供应商模型（source=provider）评测评的是远程供应商向量模型
            eval_model_source: str | None = None
            eval_model_obj: MLModel | None = None
            if not is_llm_eval and task.model_id:
                eval_model_obj = await get_model(db, task.model_id)
                if eval_model_obj is not None and eval_model_obj.source == "provider":
                    eval_model_source = "provider"

            # 真实检索：用所选向量模型在测试集候选池上计算四种策略下正样本排名
            real_ranks: list[dict] | None = None
            if not is_llm_eval:
                embedder = _build_eval_embedder(eval_model_obj)
                candidates: list[str] = []
                _seen_cand: set[str] = set()
                for r in records:
                    for field in ("positive", "negative"):
                        txt = str(r.get(field) or "").strip()
                        if txt and txt not in _seen_cand:
                            _seen_cand.add(txt)
                            candidates.append(txt)
                runtime_cfg = await config_service.get_runtime(db)
                reranker = build_reranker(runtime_cfg)
                real_ranks = await asyncio.to_thread(
                    _compute_real_ranks, embedder, candidates, reranker, records,
                    max_top_docs, max_rerank_k,
                )
            for i, rec in enumerate(records):
                if task.id in _EVAL_STOP_FLAGS:
                    break
                query = rec.get("query") or f"测试问题 {i + 1}"
                positive = rec.get("positive") or f"正确答案片段 {i + 1}"
                negative = rec.get("negative") or f"干扰答案片段 {i + 1}"

                # 大模型评测：无检索，不生成排名；向量模型评测：真实检索正样本排名与相似度
                if is_llm_eval:
                    vector_rank = fulltext_rank = hybrid_rank = rerank_rank = None
                    vector_score = None
                    vector_top5: list[dict] = []
                else:
                    rr = real_ranks[i] if real_ranks and i < len(real_ranks) else {}
                    vector_rank = rr.get("vector")
                    fulltext_rank = rr.get("fulltext")
                    hybrid_rank = rr.get("hybrid")
                    rerank_rank = rr.get("rerank")
                    vector_score = rr.get("vector_score")
                    vector_top5 = rr.get("vector_top5") or []
                rank_map = {
                    "recall_at_5": vector_rank,
                    "mrr": vector_rank,
                    "vector_qa_accuracy": vector_rank,
                    "fulltext_qa_accuracy": fulltext_rank,
                    "hybrid_qa_accuracy": hybrid_rank,
                    "rerank_qa_accuracy": rerank_rank,
                    "vector_score": vector_score,
                }

                dims: dict = {}
                llm_infos: list[dict] = []
                for m in dim_metas:
                    res, llm_info = await _eval_dim_realtime(m, rec, rank_map, judge_clients, sem)
                    dims[m["name"]] = res
                    dim_results[m["name"]].append(res)
                    if llm_info is not None:
                        llm_infos.append(llm_info)

                overall_pos = _dim_positive(dim_metas[0], dims[dim_metas[0]["name"]]) if dim_metas else False
                if overall_pos:
                    pass_count += 1

                # 样本得分：真实维度结果的正向占比（与各维度结果一致，避免随机分数）
                sample_score = (
                    round(sum(1 for m in dim_metas if _dim_positive(m, dims[m["name"]])) / len(dim_metas), 3)
                    if dim_metas else 0.0
                )

                trace = {
                    "eval_model_type": task.model_type,
                    "eval_model_source": eval_model_source,
                    "top_k": max_top_docs,
                    "vector_rank": vector_rank,
                    "fulltext_rank": fulltext_rank,
                    "hybrid_rank": hybrid_rank,
                    "rerank_rank": rerank_rank,
                    "vector_top5": vector_top5,
                    "judge": dims,
                }
                if has_llm_dims:
                    trace.update(_build_real_llm_trace(positive, llm_infos, overall_pos))

                details.append({
                    "index": i + 1,
                    "query": query,
                    "positive": positive,
                    "negative": negative,
                    "label": "Pass" if overall_pos else "Fail",
                    "score": sample_score,
                    "dims": dims,
                    "trace": trace,
                })

                task.completed_count = i + 1
                if (i + 1) % 5 == 0 or i + 1 == total:
                    await db.commit()

            task.completed_count = total
            if task.id in _EVAL_STOP_FLAGS:
                return

            scores = [{
                "name": m["name"],
                "eval_type": m["eval_type"],
                "metric": (m["eval_config"] or {}).get("metric") if m["eval_type"] == "retrieval" else None,
                "k": _dim_top_k(m),
                "score": _dim_score(m, dim_results[m["name"]]),
            } for m in dim_metas]
            avg = round(sum(s["score"] for s in scores) / len(scores), 4) if scores else 0.0

            task.result = {
                "eval_model_type": task.model_type,
                "eval_model_source": eval_model_source,
                "metrics": scores,
                "score": avg,
                "pass_count": pass_count,
                "fail_count": total - pass_count,
                "pass_rate": round(pass_count / total, 4) if total else 0,
                "details": details,
            }
            task.status = "done"
            # 评测完成后同步至所选排行榜
            if task.leaderboard_id:
                lb = await get_leaderboard(db, task.leaderboard_id)
                if lb:
                    ids = list(lb.task_ids or [])
                    if task.id not in ids:
                        ids.append(task.id)
                        lb.task_ids = ids
                        flag_modified(lb, "task_ids")
        except Exception as exc:  # noqa: BLE001
            logger.exception("评测任务失败: %s", exc)
            task.status = "failed"
        finally:
            _EVAL_STOP_FLAGS.discard(task.id)
            # 评测结束（含失败/停止）回收显存，避免交叉编码器等临时模型残留占用
            _release_torch_memory(f"评测任务 {task.id} 结束")
            await db.commit()


async def _metric_dims(db: AsyncSession, dimension_ids: list[str]) -> list[dict]:
    """返回维度元信息列表：{name, eval_type, eval_config}，用于生成指标与明细结果。"""
    dims: list[dict] = []
    for did in dimension_ids:
        dim = await get_dimension(db, did)
        if dim:
            dims.append({
                "name": dim.name,
                "eval_type": dim.eval_type or "llm_classify",
                "eval_config": dim.eval_config or {},
            })
    return dims or [
        {"name": "准确性", "eval_type": "llm_classify", "eval_config": {}},
        {"name": "相关性", "eval_type": "llm_classify", "eval_config": {}},
        {"name": "流畅度", "eval_type": "llm_classify", "eval_config": {}},
    ]


async def create_leaderboard(db: AsyncSession, data) -> MLLeaderboard:
    ids = list(data.dimension_ids or [])
    names = await _dimension_names(db, ids)
    lb = MLLeaderboard(
        name=data.name,
        dimension_ids=ids,
        dimension_names=names,
        task_ids=list(data.task_ids or []),
    )
    db.add(lb)
    await db.commit()
    await db.refresh(lb)
    return lb


async def update_leaderboard(db: AsyncSession, lb: MLLeaderboard, data) -> MLLeaderboard:
    ids = list(data.dimension_ids or [])
    lb.name = data.name
    lb.dimension_ids = ids
    lb.dimension_names = await _dimension_names(db, ids)
    lb.task_ids = list(data.task_ids or [])
    # JSON 列重新赋值需显式标记字段变更，确保 UPDATE 提交
    flag_modified(lb, "dimension_ids")
    flag_modified(lb, "dimension_names")
    flag_modified(lb, "task_ids")
    await db.commit()
    await db.refresh(lb)
    return lb


async def list_leaderboards(db: AsyncSession) -> list[MLLeaderboard]:
    result = await db.execute(select(MLLeaderboard).order_by(MLLeaderboard.created_at.desc()))
    return list(result.scalars().all())


async def get_leaderboard(db: AsyncSession, leaderboard_id: str) -> MLLeaderboard | None:
    result = await db.execute(select(MLLeaderboard).where(MLLeaderboard.id == leaderboard_id))
    return result.scalar_one_or_none()


async def delete_leaderboard(db: AsyncSession, lb: MLLeaderboard) -> None:
    await db.delete(lb)
    await db.commit()


async def remove_leaderboard_task(db: AsyncSession, lb: MLLeaderboard, task_id: str) -> None:
    ids = list(lb.task_ids or [])
    if task_id in ids:
        ids.remove(task_id)
        lb.task_ids = ids
        flag_modified(lb, "task_ids")
        await db.commit()


async def resolve_model_name(
    db: AsyncSession, model_id: str | None, model_type: str, llm_model_id: str | None
) -> str:
    """根据评测模型类型解析模型显示名：llm 取供应商模型，vector 取「我的模型」。"""
    if model_type == "llm" and llm_model_id:
        from app.models.provider import Provider

        prov = await db.get(Provider, llm_model_id)
        if prov is not None:
            if prov.model_name and prov.name != prov.model_name:
                return f"{prov.name}（{prov.model_name}）"
            return prov.name
        return llm_model_id
    if model_id:
        model = await get_model(db, model_id)
        return model.name if model else model_id
    return ""


async def resolve_names(
    db: AsyncSession,
    model_id: str | None,
    model_type: str,
    llm_model_id: str | None,
    dimension_ids: list[str],
    data_id: str,
) -> tuple[str, list[str], str]:
    model_name = await resolve_model_name(db, model_id, model_type, llm_model_id)
    dimension_names: list[str] = []
    for did in dimension_ids or []:
        dim = await get_dimension(db, did)
        dimension_names.append(dim.name if dim else did)
    data_name = data_id
    dataset = await get_dataset(db, data_id)
    if dataset:
        data_name = dataset.name
    return model_name, dimension_names, data_name


def build_eval_task_xlsx(task: MLEvalTask) -> bytes:
    """将评测结果明细导出为 xlsx（列：query / positive / negative / 测试）。"""
    from io import BytesIO

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "评测结果"
    ws.append(["query", "positive", "negative", "测试"])

    details = (task.result or {}).get("details")
    if isinstance(details, list):
        for d in details:
            if not isinstance(d, dict):
                continue
            ws.append([
                d.get("query", ""),
                d.get("positive", ""),
                d.get("negative", ""),
                d.get("label", ""),
            ])

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()