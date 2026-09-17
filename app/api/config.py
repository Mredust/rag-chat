"""系统配置管理路由。"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import success_response
from app.core.security import get_current_user_id
from app.db.database import get_db
from app.schemas.system import SystemConfigItem, SystemConfigListResponse, SystemConfigUpdate
from app.services import config_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/config", summary="配置列表（敏感项脱敏）")
async def list_config(
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    rows = await config_service.list_config(db)
    items = [SystemConfigItem(**r) for r in rows]
    return success_response(
        data=SystemConfigListResponse(configs=items, total=len(items)).model_dump(mode="json")
    )


@router.put("/config/{key}", summary="新增/更新配置")
async def set_config(
    key: str,
    data: SystemConfigUpdate,
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    logger.info("更新配置请求: key=%s, is_secret=%s", key, data.is_secret)
    await config_service.set_config(db, key, data.value, data.is_secret)
    logger.info("配置已更新: key=%s", key)
    return success_response(message="保存成功")