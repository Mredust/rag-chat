"""系统配置中心：CRUD + 敏感项加密 + 运行时热加载缓存。

配置项读取顺序：数据库（SystemConfig 表）覆盖 .env 默认值；任一写操作后
清除内存缓存，下次读取时重新加载，实现「运行时热加载」。
"""
from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.system import SystemConfig
from app.utils.paths import to_rel_path

logger = logging.getLogger(__name__)

# ---- 内置默认值 ----
DEFAULT_PROMPT_SYSTEM = "你是一个乐于助人的智能助手，请用简洁准确的语言回答用户问题。"

DEFAULT_PROMPT_RAG = (
    "你是一个基于知识库的智能问答助手。请严格依据下方【知识片段】回答问题，"
    "用简洁、清晰的语言组织答案，不要逐字复述原文，也不要输出与问题无关的内容；"
    "若【知识片段】中没有相关信息，请直接说明「知识库中未找到相关内容」。\n\n"
    "【知识片段】\n{context}\n\n"
    "【用户问题】\n{question}\n\n"
    "【回答】"
)

# 敏感配置项（如 API Key），加密存储、接口不返回明文
SECRET_KEYS = {"llm_api_key", "embedding_api_key"}

# 路径类配置项：入库时统一转为项目根目录下的相对路径
PATH_KEYS = {"rerank_model"}

# 运行时配置缓存（进程内）
_runtime_cache: dict[str, str] | None = None


def _defaults() -> dict[str, str]:
    return {
        "llm_api_base": settings.LLM_API_BASE,
        "llm_api_key": settings.LLM_API_KEY,
        "llm_model": settings.LLM_MODEL,
        # 多模型兜底列表（逗号分隔），为空时回退 llm_model
        "llm_models": "",
        "llm_timeout": "120",
        "llm_max_retries": "1",
        "embedding_api_base": settings.EMBEDDING_API_BASE,
        "embedding_api_key": settings.EMBEDDING_API_KEY,
        "embedding_model": settings.EMBEDDING_MODEL,
        "embedding_dim": str(settings.EMBEDDING_DIM),
        "retrieval_mode": "hybrid",
        "top_k": "5",
        "similarity_threshold": "0.0",
        "chunk_size": "512",
        "chunk_overlap": "50",
        "rerank_enabled": "true",
        "rerank_model": "rerankers/bge-reranker-base",
        "rerank_top_m": "20",
        "rrf_k": "60",
        "prompt_system": DEFAULT_PROMPT_SYSTEM,
        "prompt_rag": DEFAULT_PROMPT_RAG,
        "max_tokens": "2048",
        "rag_context_max_chars": "3000",
    }


def _fernet() -> Fernet:
    """由 JWT_SECRET 派生对称加密密钥。"""
    key = hashlib.sha256(settings.JWT_SECRET.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(value: str) -> str:
    if not value:
        return value
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt(value: str) -> str:
    if not value:
        return value
    try:
        return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        # 密钥变更导致无法解密时，回退为原始值
        return value


def mask(value: str) -> str:
    """脱敏展示：非空则显示掩码。"""
    return "******" if value else ""


def invalidate_cache() -> None:
    global _runtime_cache
    _runtime_cache = None


async def list_config(db: AsyncSession) -> list[dict]:
    """列出全部可配置项（默认值 + 数据库覆盖，敏感项值已脱敏）。"""
    result = await db.execute(select(SystemConfig))
    rows = {r.key: r for r in result.scalars().all()}
    defaults = _defaults()

    keys = list(defaults.keys()) + [k for k in rows if k not in defaults]
    items: list[dict] = []
    for key in keys:
        row = rows.get(key)
        is_secret = key in SECRET_KEYS
        if row is not None:
            is_secret = row.is_secret
            raw = row.value
            value = mask(raw) if (is_secret and raw) else raw
            updated_at = row.updated_at
        else:
            value = defaults[key]
            if is_secret and value:
                value = mask(value)
            updated_at = None
        items.append({"key": key, "value": value, "is_secret": is_secret, "updated_at": updated_at})
    return items


async def set_config(db: AsyncSession, key: str, value: str, is_secret: bool) -> SystemConfig:
    """新增/更新配置项；敏感项加密存储，路径项存相对路径，写后清除缓存。"""
    if key in PATH_KEYS and value and not is_secret:
        value = to_rel_path(value)
    result = await db.execute(select(SystemConfig).where(SystemConfig.key == key))
    row = result.scalar_one_or_none()
    stored = encrypt(value) if is_secret else value
    if row is None:
        row = SystemConfig(key=key, value=stored, is_secret=is_secret)
        db.add(row)
    else:
        row.value = stored
        row.is_secret = is_secret
    await db.commit()
    await db.refresh(row)
    invalidate_cache()
    return row


async def get_runtime(db: AsyncSession) -> dict[str, str]:
    """返回运行时配置（默认值 + 数据库覆盖，敏感项已解密），带进程内缓存。"""
    global _runtime_cache
    if _runtime_cache is not None:
        return _runtime_cache

    merged = _defaults()
    result = await db.execute(select(SystemConfig))
    for row in result.scalars().all():
        if row.is_secret:
            merged[row.key] = decrypt(row.value)
        else:
            merged[row.key] = row.value

    # 激活的供应商覆盖默认 LLM 配置（多供应商切换）
    from app.models.provider import Provider

    active = (
        await db.execute(select(Provider).where(Provider.is_active.is_(True)))
    ).scalars().first()
    if active is not None:
        merged["llm_api_base"] = active.api_base
        merged["llm_api_key"] = decrypt(active.api_key)
        merged["llm_model"] = active.model_name
        # 多模型兜底列表：优先使用 model_names，回退到单个 model_name
        names = list(active.model_names or [])
        if not names and active.model_name:
            names = [active.model_name]
        merged["llm_models"] = ",".join(names)

    _runtime_cache = merged
    logger.debug("运行时配置已加载（缓存重建）: %d 项", len(merged))
    return merged


def get_int(cfg: dict[str, str], key: str, default: int) -> int:
    try:
        return int(cfg.get(key, "").strip() or default)
    except ValueError:
        return default


def get_float(cfg: dict[str, str], key: str, default: float) -> float:
    try:
        return float(cfg.get(key, "").strip() or default)
    except ValueError:
        return default