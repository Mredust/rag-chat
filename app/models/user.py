"""用户模型。"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class User(Base):
    __tablename__ = "user"

    # 主键（UUID 字符串）
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: str(uuid.uuid4()))
    # 邮箱（唯一）
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    # 密码（bcrypt 哈希）
    password: Mapped[str] = mapped_column(String(255), nullable=False)
    # 用户名（唯一）
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    # 头像 URL
    avatar: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 个人简介
    introduction: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 状态（active / disabled）
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    # 创建时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )
    # 更新时间
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), onupdate=func.now(), nullable=False
    )