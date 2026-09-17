"""大模型供应商相关 Schema。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ProviderBase(BaseModel):
    # 供应商名称
    name: str = Field(..., min_length=1, max_length=64)
    # 供应商类型（deepseek / openai / custom）
    api_type: str = Field("custom", max_length=16)
    # OpenAI 兼容 base_url
    api_base: str = Field("", max_length=500)
    # 模型名称（兼容旧字段，取 model_names 第一个）
    model_name: str = Field("", max_length=128)
    # 多个模型名称（按顺序兜底访问）
    model_names: list[str] = Field(default_factory=list)


class ProviderCreate(ProviderBase):
    # API Key（创建时填写，加密存储）
    api_key: str = Field("", max_length=500)


class ProviderUpdate(ProviderBase):
    # API Key（None 或空串表示不修改）
    api_key: str | None = None


class ProviderResponse(BaseModel):
    id: str
    name: str
    api_type: str
    api_base: str
    model_name: str
    model_names: list[str] = Field(default_factory=list)
    is_active: bool
    # 是否已配置 API Key（接口不返回明文）
    has_key: bool
    # 脱敏后的 API Key（如 sk-23sd********2343），用于回填展示
    masked_key: str = ""
    created_at: datetime

    model_config = {"from_attributes": True}


class ProviderListResponse(BaseModel):
    providers: list[ProviderResponse]
    total: int