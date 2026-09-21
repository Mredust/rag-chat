"""知识库模型：知识空间、文档与切片。"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class DocumentStatus(str, Enum):
    """文档处理状态。"""

    PENDING = "待处理"
    PARSING = "解析中"
    CHUNKING = "切片中"
    EMBEDDING = "向量化中"
    COMPLETED = "已完成"
    FAILED = "失败"


class KnowledgeSpace(Base):
    __tablename__ = "knowledge_space"

    # 主键（UUID 字符串）
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: str(uuid.uuid4()))
    # 所属用户 ID
    user_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 空间名称
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # 空间描述
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # 创建时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )
    # 更新时间
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), onupdate=func.now(), nullable=False
    )

    # 空间下的文档（关系）
    documents: Mapped[list["Document"]] = relationship(
        back_populates="space", cascade="all, delete-orphan"
    )


class Document(Base):
    __tablename__ = "document"

    # 主键（UUID 字符串）
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: str(uuid.uuid4()))
    # 所属知识空间 ID
    space_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("knowledge_space.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 文件名
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # 文件类型（pdf / docx / txt / md）
    file_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # 文件大小（字节）
    file_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 存储路径
    storage_path: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    # 处理状态（见 DocumentStatus）
    status: Mapped[str] = mapped_column(
        String(16), default=DocumentStatus.PENDING.value, nullable=False, index=True
    )
    # 失败原因
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 切片数量
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 总字符数
    char_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 切片大小
    chunk_size: Mapped[int] = mapped_column(Integer, default=512, nullable=False)
    # 切片重叠
    chunk_overlap: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    # 向量化模型
    embedding_model: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    # 创建时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )
    # 处理完成时间
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # 所属空间（关系）
    space: Mapped["KnowledgeSpace"] = relationship(back_populates="documents")
    # 文档下的切片（关系）
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class Chunk(Base):
    __tablename__ = "chunk"

    # 主键（UUID 字符串）
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: str(uuid.uuid4()))
    # 所属文档 ID
    document_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("document.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 所属知识空间 ID（冗余，便于按空间过滤）
    space_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    # 切片序号
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # 切片内容
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 字符数
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # 额外元信息（JSON，如来源段落等）
    meta: Mapped[dict] = mapped_column("metadata", JSON, default=dict, nullable=False)
    # 向量化模型
    embedding_model: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    # 创建时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )

    # 所属文档（关系）
    document: Mapped["Document"] = relationship(back_populates="chunks")