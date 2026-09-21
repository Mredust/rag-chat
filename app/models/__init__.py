"""SQLAlchemy 模型聚合：Base 与全部表模型。

导入本包即完成所有模型的注册，`Base.metadata` 将包含全部表定义，
供 Alembic 迁移与运行时建表使用。
"""
from __future__ import annotations

from app.models.base import Base
from app.models.chat import ChatMessage, ChatSession
from app.models.knowledge import Chunk, Document, DocumentStatus, KnowledgeSpace
from app.models.ml import (
    MLDataset,
    MLDatasetVersion,
    MLEvalDimension,
    MLEvalTask,
    MLModel,
    MLTrainTask,
)
from app.models.provider import Provider
from app.models.system import SystemConfig
from app.models.user import User

__all__ = [
    "Base",
    "User",
    "KnowledgeSpace",
    "Document",
    "Chunk",
    "DocumentStatus",
    "ChatSession",
    "ChatMessage",
    "SystemConfig",
    "Provider",
    "MLDataset",
    "MLDatasetVersion",
    "MLModel",
    "MLTrainTask",
    "MLEvalDimension",
    "MLEvalTask",
]