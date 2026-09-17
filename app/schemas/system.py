"""系统配置相关 Schema。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SystemConfigItem(BaseModel):
    key: str
    value: str
    is_secret: bool
    updated_at: datetime | None = None


class SystemConfigListResponse(BaseModel):
    configs: list[SystemConfigItem]
    total: int


class SystemConfigUpdate(BaseModel):
    value: str = Field(..., max_length=20000)
    # 是否敏感项（敏感项将加密存储，接口返回掩码）
    is_secret: bool = False