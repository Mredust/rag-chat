"""用户业务逻辑：注册、认证、查询、更新。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.models.user import User
from app.schemas.auth import UserRegister, UserUpdate


async def get_by_id(db: AsyncSession, user_id: str) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_by_username(db: AsyncSession, username: str) -> User | None:
    result = await db.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def get_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def create_user(db: AsyncSession, data: UserRegister) -> User:
    user = User(username=data.username, email=data.email, password=hash_password(data.password))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate(db: AsyncSession, account: str, password: str) -> User | None:
    # 支持用户名或邮箱登录
    user = await get_by_username(db, account)
    if user is None:
        user = await get_by_email(db, account)
    if not user or not verify_password(password, user.password):
        return None
    return user


async def update_user(db: AsyncSession, user: User, data: UserUpdate) -> User:
    payload = data.model_dump(exclude_unset=True)
    for key, value in payload.items():
        setattr(user, key, value)
    await db.commit()
    await db.refresh(user)
    return user