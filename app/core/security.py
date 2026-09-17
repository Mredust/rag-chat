"""认证与安全：密码哈希、JWT 签发/校验、当前用户依赖注入。

JWT 采用 HS256，基于标准库 hmac/hashlib 实现，无需额外依赖。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import bcrypt
from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.response import BusinessError, ErrorCode
from app.db.database import get_db
from app.models.user import User

# ========== 密码哈希 ==========


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


# ========== JWT（HS256） ==========


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_access_token(user_id: str, expires_minutes: int | None = None) -> str:
    minutes = expires_minutes if expires_minutes is not None else settings.ACCESS_TOKEN_EXPIRE_MINUTES
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": user_id, "type": "access", "iat": now, "exp": now + minutes * 60}

    signed_input = (
        _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    )
    signature = hmac.new(settings.JWT_SECRET.encode(), signed_input.encode(), hashlib.sha256).digest()
    return signed_input + "." + _b64url_encode(signature)


def decode_access_token(token: str) -> dict:
    """解码并校验 JWT，失败抛 BusinessError(401)。"""
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
    except ValueError:
        raise BusinessError(ErrorCode.TOKEN_INVALID, http_status=401)

    signed_input = f"{header_b64}.{payload_b64}"
    expected_sig = hmac.new(settings.JWT_SECRET.encode(), signed_input.encode(), hashlib.sha256).digest()
    try:
        provided_sig = _b64url_decode(sig_b64)
    except Exception:
        raise BusinessError(ErrorCode.TOKEN_INVALID, http_status=401)

    if not hmac.compare_digest(expected_sig, provided_sig):
        raise BusinessError(ErrorCode.TOKEN_INVALID, http_status=401)

    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except Exception:
        raise BusinessError(ErrorCode.TOKEN_INVALID, http_status=401)

    if payload.get("exp", 0) < int(time.time()):
        raise BusinessError(ErrorCode.TOKEN_EXPIRED, http_status=401)

    return payload


# ========== FastAPI 依赖注入 ==========


async def get_current_user_id(authorization: str | None = Header(default=None)) -> str:
    """从 Authorization Bearer 头解析当前用户 ID。"""
    if not authorization:
        raise BusinessError(ErrorCode.TOKEN_INVALID, http_status=401)

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise BusinessError(ErrorCode.TOKEN_INVALID, http_status=401)

    payload = decode_access_token(parts[1])
    user_id = payload.get("sub")
    if not user_id:
        raise BusinessError(ErrorCode.TOKEN_INVALID, http_status=401)
    return user_id


async def get_current_user(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> User:
    """返回当前登录用户 ORM 对象。"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise BusinessError(ErrorCode.USER_NOT_FOUND, http_status=404)
    return user