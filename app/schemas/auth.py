"""认证与用户相关 Schema。"""
from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


class UserRegister(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=6, max_length=128)
    email: str = Field(..., max_length=255)

    @field_validator("username")
    @classmethod
    def _check_username(cls, v: str) -> str:
        if not v.replace("_", "").isalnum():
            raise ValueError("用户名只能包含字母、数字和下划线")
        return v

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str) -> str:
        if not _EMAIL_RE.match(v):
            raise ValueError("邮箱格式不正确")
        return v


class UserLogin(BaseModel):
    # 登录账号：用户名或邮箱
    username: str = Field(..., max_length=255)
    password: str = Field(..., max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserInfo(BaseModel):
    id: str
    username: str
    email: str
    avatar: str | None = None
    introduction: str | None = None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    avatar: str | None = Field(None, max_length=500)
    introduction: str | None = Field(None, max_length=2000)