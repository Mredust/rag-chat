"""大模型供应商管理路由。"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import BusinessError, ErrorCode, success_response
from app.core.security import get_current_user_id
from app.db.database import get_db
from app.schemas.provider import (
    ProviderCreate,
    ProviderListResponse,
    ProviderResponse,
    ProviderUpdate,
)
from app.services import provider_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/providers", summary="供应商列表")
async def list_providers(
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    rows = await provider_service.list_providers(db)
    items = [ProviderResponse(**r) for r in rows]
    return success_response(
        data=ProviderListResponse(providers=items, total=len(items)).model_dump(mode="json")
    )


@router.post("/providers", summary="新增供应商")
async def create_provider(
    data: ProviderCreate,
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    logger.info("新增供应商请求: name=%s, model=%s, api_type=%s", data.name, data.model_name, data.api_type)
    p = await provider_service.create_provider(db, data)
    logger.info("供应商创建成功: provider_id=%s, is_active=%s", p.id, p.is_active)
    return success_response(data=ProviderResponse(**provider_service.serialize(p)).model_dump(mode="json"))


@router.put("/providers/{provider_id}", summary="更新供应商")
async def update_provider(
    provider_id: str,
    data: ProviderUpdate,
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    p = await provider_service.update_provider(db, provider_id, data)
    if p is None:
        raise BusinessError(ErrorCode.PROVIDER_NOT_FOUND, http_status=404)
    return success_response(data=ProviderResponse(**provider_service.serialize(p)).model_dump(mode="json"))


@router.delete("/providers/{provider_id}", summary="删除供应商")
async def delete_provider(
    provider_id: str,
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    ok = await provider_service.delete_provider(db, provider_id)
    if not ok:
        raise BusinessError(ErrorCode.PROVIDER_NOT_FOUND, http_status=404)
    return success_response(message="删除成功")


@router.post("/providers/{provider_id}/activate", summary="切换启用供应商")
async def activate_provider(
    provider_id: str,
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    logger.info("切换启用供应商请求: provider_id=%s", provider_id)
    p = await provider_service.activate_provider(db, provider_id)
    if p is None:
        raise BusinessError(ErrorCode.PROVIDER_NOT_FOUND, http_status=404)
    logger.info("供应商已切换启用: provider_id=%s, name=%s", p.id, p.name)
    return success_response(data=ProviderResponse(**provider_service.serialize(p)).model_dump(mode="json"))


@router.post("/providers/{provider_id}/deactivate", summary="停用供应商")
async def deactivate_provider(
    provider_id: str,
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    logger.info("停用供应商请求: provider_id=%s", provider_id)
    p = await provider_service.deactivate_provider(db, provider_id)
    if p is None:
        raise BusinessError(ErrorCode.PROVIDER_NOT_FOUND, http_status=404)
    logger.info("供应商已停用: provider_id=%s, name=%s", p.id, p.name)
    return success_response(data=ProviderResponse(**provider_service.serialize(p)).model_dump(mode="json"))