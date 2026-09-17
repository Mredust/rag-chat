"""Chroma 向量库访问封装：统一提供客户端与集合入口。

向量数据（文档切片 embedding）存储于 Chroma，通过 document_id 与 MySQL 中的
切片（chunk）关联；MySQL 负责业务/关系数据，Chroma 负责向量相似性检索。
"""
from __future__ import annotations

import logging
from functools import lru_cache

import chromadb

from app.core.config import settings

logger = logging.getLogger(__name__)


@lru_cache
def get_client() -> chromadb.ClientAPI:
    """返回全局共享的 Chroma 持久化客户端（本地目录模式）。"""
    client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
    logger.info("向量库准备：Chroma 持久化客户端已连接 (path=%s)", settings.CHROMA_PERSIST_DIR)
    return client


def get_collection(name: str | None = None) -> chromadb.Collection:
    """获取（不存在则创建）指定集合，默认使用配置中的知识库集合。"""
    collection_name = name or settings.CHROMA_COLLECTION
    collection = get_client().get_or_create_collection(name=collection_name)
    logger.debug("向量库集合就绪: %s", collection_name)
    return collection