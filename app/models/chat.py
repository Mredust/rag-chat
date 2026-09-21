"""会话与消息模型：用于存储 RAG 问答 / Agent 助手的历史记录。"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.mysql import DATETIME as MySQLDATETIME
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    # 主键（UUID 字符串）
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: str(uuid.uuid4()))
    # 所属用户 ID
    user_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 关联的知识空间 ID（RAG 问答上下文，可为空）
    space_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # 会话标题
    title: Mapped[str] = mapped_column(String(255), default="新会话", nullable=False)
    # 创建时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )
    # 更新时间
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), onupdate=func.now(), nullable=False
    )

    # 会话下的消息（关系）
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="ChatMessage.id"
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    # 主键（自增整数，单调递增，保证消息写入顺序稳定可排序）
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 所属会话 ID
    conversation_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 角色（user / assistant / system / tool）
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    # 消息内容
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 引用来源（JSON 数组：切片 id / 文档 id / 片段文本等）
    citations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 创建时间（微秒精度，保证同一秒内先后写入的用户/助手消息可稳定排序）
    created_at: Mapped[datetime] = mapped_column(
        MySQLDATETIME(fsp=6), default=datetime.now, nullable=False
    )

    # 所属会话（关系）
    session: Mapped["ChatSession"] = relationship(back_populates="messages")