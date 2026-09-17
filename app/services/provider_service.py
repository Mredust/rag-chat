"""大模型供应商服务：CRUD + 切换激活 + 敏感项加密存储。

激活切换会清空运行时配置缓存，使 RAG/Agent 在下次请求时自动使用新供应商。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.provider import Provider
from app.schemas.provider import ProviderCreate, ProviderUpdate
from app.services.config_service import decrypt, encrypt, invalidate_cache


def _mask_key(value: str) -> str:
    """将 API Key 脱敏为 sk-23sd********2343 形式（保留前 6 后 4 位）。"""
    if not value:
        return ""
    if len(value) <= 10:
        return value[:1] + "*" * 8 + value[-1:]
    return value[:6] + "*" * 8 + value[-4:]


def serialize(p: Provider) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "api_type": p.api_type,
        "api_base": p.api_base,
        "model_name": p.model_name,
        "model_names": list(p.model_names or []),
        "is_active": p.is_active,
        "has_key": bool(p.api_key),
        "masked_key": _mask_key(decrypt(p.api_key)) if p.api_key else "",
        "created_at": p.created_at,
    }


async def list_providers(db: AsyncSession) -> list[dict]:
    result = await db.execute(select(Provider).order_by(Provider.created_at))
    return [serialize(p) for p in result.scalars().all()]


async def get_provider(db: AsyncSession, provider_id: str) -> Provider | None:
    result = await db.execute(select(Provider).where(Provider.id == provider_id))
    return result.scalar_one_or_none()


def _normalize_models(model_name: str, model_names: list[str] | None) -> tuple[str, list[str]]:
    """将模型列表去重/去空；model_name 始终取列表第一个，保证兼容。"""
    names: list[str] = []
    for m in (model_names or []):
        m = str(m or "").strip()
        if m and m not in names:
            names.append(m)
    if not names and model_name:
        names.append(model_name)
    first = names[0] if names else (model_name or "")
    return first, names


async def create_provider(db: AsyncSession, data: ProviderCreate) -> Provider:
    first, names = _normalize_models(data.model_name, data.model_names)
    p = Provider(
        name=data.name,
        api_type=data.api_type,
        api_base=data.api_base,
        api_key=encrypt(data.api_key) if data.api_key else "",
        model_name=first,
        model_names=names,
    )
    db.add(p)
    await db.flush()
    # 若当前没有激活供应商，则默认激活新供应商
    has_active = (
        await db.execute(select(Provider).where(Provider.is_active.is_(True)))
    ).scalar_one_or_none()
    if has_active is None:
        p.is_active = True
    await db.commit()
    await db.refresh(p)
    invalidate_cache()
    return p


async def update_provider(db: AsyncSession, provider_id: str, data: ProviderUpdate) -> Provider | None:
    p = await get_provider(db, provider_id)
    if p is None:
        return None
    p.name = data.name
    p.api_type = data.api_type
    p.api_base = data.api_base
    first, names = _normalize_models(data.model_name, data.model_names)
    p.model_name = first
    p.model_names = names
    if data.api_key:  # 仅在显式填写时更新 Key
        p.api_key = encrypt(data.api_key)
    await db.commit()
    await db.refresh(p)
    invalidate_cache()
    return p


async def delete_provider(db: AsyncSession, provider_id: str) -> bool:
    p = await get_provider(db, provider_id)
    if p is None:
        return False
    was_active = p.is_active
    await db.delete(p)
    await db.flush()
    # 若删除的是激活供应商，则顺位激活剩余第一个
    if was_active:
        first = (
            await db.execute(select(Provider).order_by(Provider.created_at))
        ).scalars().first()
        if first is not None:
            first.is_active = True
    await db.commit()
    invalidate_cache()
    return True


async def activate_provider(db: AsyncSession, provider_id: str) -> Provider | None:
    p = await get_provider(db, provider_id)
    if p is None:
        return None
    rows = (await db.execute(select(Provider))).scalars().all()
    for row in rows:
        row.is_active = row.id == provider_id
    await db.commit()
    await db.refresh(p)
    invalidate_cache()
    return p


async def deactivate_provider(db: AsyncSession, provider_id: str) -> Provider | None:
    """停用供应商：置为未激活，后续请求不再使用（不自动激活其它供应商）。"""
    p = await get_provider(db, provider_id)
    if p is None:
        return None
    p.is_active = False
    await db.commit()
    await db.refresh(p)
    invalidate_cache()
    return p


async def get_active_provider(db: AsyncSession) -> Provider | None:
    result = await db.execute(select(Provider).where(Provider.is_active.is_(True)))
    return result.scalars().first()


def active_llm_config(p: Provider) -> tuple[str, str, str]:
    """返回激活供应商的 (api_base, api_key, model_name)，key 已解密。"""
    return p.api_base, decrypt(p.api_key), p.model_name