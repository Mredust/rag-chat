"""异步数据库引擎与会话工厂。"""
from __future__ import annotations
import logging
from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.core.config import settings

logger = logging.getLogger(__name__)

# 异步引擎（asyncmy）
engine = create_async_engine(
    url=settings.database_url,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,  # 连接前Ping检测
    pool_recycle=3600,  # 连接回收时间
    echo=False,  # 生产环境关闭SQL日志
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：请求级会话，异常自动回滚。"""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """初始化数据库：执行 Alembic 迁移到最新版本。"""
    import asyncio
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    # 执行迁移（独立线程，内部自建异步引擎，避免跨事件循环复用连接）
    alembic_ini = Path(__file__).resolve().parents[2] / "alembic.ini"
    cfg = Config(str(alembic_ini))
    await asyncio.to_thread(command.upgrade, cfg, "head")
    logger.info("数据库迁移完成 (alembic upgrade head)")


async def close_db() -> None:
    """释放数据库连接池。"""
    await engine.dispose()
    logger.info("数据库连接池已关闭")
