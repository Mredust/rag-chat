"""Alembic 迁移环境：使用异步引擎连接 MySQL，元数据来自 app.models。"""
from __future__ import annotations
import asyncio
import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import settings
from app.models import Base

# Alembic Config 对象
config = context.config

# 配置日志
# 应用启动时 main.py 已通过 setup_logging() 配置根日志；此时再调用 fileConfig 会
# 覆盖根 logger（级别/handler）并禁用未在 alembic.ini 声明的应用 logger，
# 导致迁移完成后应用日志全部静默（与 rag-learn 实测 2026-08-09 结论一致）。
# 因此仅当根日志尚未配置（如命令行单独执行 alembic upgrade）时才调用 fileConfig。
if config.config_file_name is not None and not getattr(logging.getLogger(), "_rag_chat_configured", False):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# 注入数据库地址（来自 .env），覆盖 alembic.ini 中的占位符
config.set_main_option("sqlalchemy.url", settings.database_url)

# 目标元数据：所有已注册模型的表
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式：仅生成 SQL，不真正连接数据库。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """在线模式：使用异步引擎执行迁移。"""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
