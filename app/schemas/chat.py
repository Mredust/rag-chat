"""会话、消息与问答相关 Schema。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ConversationResponse(BaseModel):
    id: str
    space_id: str | None = None
    title: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConversationListResponse(BaseModel):
    conversations: list[ConversationResponse]
    total: int


class MessageResponse(BaseModel):
    id: int
    conversation_id: str
    role: str
    content: str
    citations: list | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class MessageListResponse(BaseModel):
    messages: list[MessageResponse]
    total: int


class ChatRequest(BaseModel):
    """RAG 问答请求。"""

    question: str = Field(..., min_length=1, max_length=10000)
    conversation_id: str | None = None
    space_id: str | None = None
    # 可选：新建会话时的标题（默认使用问题前若干字）
    title: str | None = None