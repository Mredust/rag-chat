"""系统配置模型：存储系统级配置项，支持敏感项加密存储与运行时热加载。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SystemConfig(Base):
    __tablename__ = "system_config"

    # 配置项键（主键，如 retrieval_mode / top_k / llm_api_key）
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    # 配置值（字符串；敏感项为加密后的密文）
    value: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # 是否为敏感项（如 API Key，需加密存储、接口不返回明文）
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # 更新时间
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), onupdate=func.now(), nullable=False
    )