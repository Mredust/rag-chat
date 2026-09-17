"""认证与用户路由。"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.response import BusinessError, ErrorCode, success_response
from app.core.security import create_access_token, get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.auth import TokenResponse, UserInfo, UserLogin, UserRegister, UserUpdate
from app.services import user_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/auth/register", summary="用户注册")
async def register(data: UserRegister, db: AsyncSession = Depends(get_db)):
    logger.info("注册请求: username=%s, email=%s", data.username, data.email)
    if await user_service.get_by_username(db, data.username):
        raise BusinessError(ErrorCode.USERNAME_EXISTS, http_status=409)
    if await user_service.get_by_email(db, data.email):
        raise BusinessError(ErrorCode.EMAIL_EXISTS, http_status=409)

    user = await user_service.create_user(db, data)
    logger.info("用户注册成功: username=%s, id=%s", data.username, user.id)
    return success_response(data=UserInfo.model_validate(user).model_dump(mode="json"))


@router.post("/auth/login", summary="用户登录")
async def login(data: UserLogin, db: AsyncSession = Depends(get_db)):
    logger.info("登录请求: username=%s", data.username)
    user = await user_service.authenticate(db, data.username, data.password)
    if not user:
        logger.warning("登录失败: username=%s", data.username)
        raise BusinessError(ErrorCode.PASSWORD_ERROR, http_status=401)

    token = create_access_token(user.id)
    logger.info("用户登录成功: username=%s, id=%s", data.username, user.id)
    return success_response(
        data=TokenResponse(
            access_token=token,
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        ).model_dump()
    )


@router.get("/user/me", summary="获取当前用户信息")
async def get_me(user: User = Depends(get_current_user)):
    return success_response(data=UserInfo.model_validate(user).model_dump(mode="json"))


@router.put("/user/me", summary="更新当前用户信息")
async def update_me(
    data: UserUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    updated = await user_service.update_user(db, user, data)
    return success_response(data=UserInfo.model_validate(updated).model_dump(mode="json"))