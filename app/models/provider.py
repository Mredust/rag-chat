"""大模型供应商模型：支持多供应商（DeepSeek / OpenAI 等）管理与切换。"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Provider(Base):
    __tablename__ = "provider"

    # 主键（UUID 字符串）
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: str(uuid.uuid4()))
    # 供应商名称（如 DeepSeek / OpenAI）
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    # 供应商类型（deepseek / openai / custom），用于前端预填默认地址与模型
    api_type: Mapped[str] = mapped_column(String(16), default="custom", nullable=False)
    # API 地址（OpenAI 兼容 base_url）
    api_base: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    # API Key（加密存储的密文）
    api_key: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # 模型名称（兼容旧数据：取 model_names 第一个，或单独维护的主模型名）
    model_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    # 多个模型名称（按顺序兜底访问：前一个上游错误/额度耗尽后切换下一个）
    model_names: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # 是否当前启用（同一时刻有且仅有一个激活）
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # 创建时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )