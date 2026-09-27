"""Chroma 向量库访问封装：统一提供客户端与集合入口。

向量数据（文档切片 embedding）存储于 Chroma，通过 document_id 与 MySQL 中的
切片（chunk）关联；MySQL 负责业务/关系数据，Chroma 负责向量相似性检索。
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import chromadb

from app.core.config import BASE_DIR, settings

logger = logging.getLogger(__name__)


def _resolve_persist_dir() -> str:
    """Chroma 持久化目录转绝对路径（相对路径按项目根解析）。

    相对路径会随进程启动目录（CWD）漂移：不同方式启动时会连到不同的 Chroma 库，
    造成「MySQL 有切片但向量库为空」的检索命中为 0 问题。
    """
    path = Path(settings.CHROMA_PERSIST_DIR)
    if not path.is_absolute():
        path = BASE_DIR / path
    return str(path)


@lru_cache
def get_client() -> chromadb.ClientAPI:
    """返回全局共享的 Chroma 持久化客户端（本地目录模式）。"""
    persist_dir = _resolve_persist_dir()
    client = chromadb.PersistentClient(path=persist_dir)
    logger.info("向量库准备：Chroma 持久化客户端已连接 (path=%s)", persist_dir)
    return client


def get_collection(name: str | None = None) -> chromadb.Collection:
    """获取（不存在则创建）指定集合，默认使用配置中的知识库集合。"""
    collection_name = name or settings.CHROMA_COLLECTION
    collection = get_client().get_or_create_collection(name=collection_name)
    logger.debug("向量库集合就绪: %s", collection_name)
    return collection