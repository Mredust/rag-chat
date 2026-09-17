"""RAG Chat 应用入口：路由注册、CORS、生命周期（数据库初始化）、请求日志。

启动阶段：初始化日志 → 数据库迁移 → CORS → 异常处理器；关闭阶段释放资源。
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.core.config import settings
from app.core.logger_handler import setup_logging
from app.core.response import register_exception_handlers
from app.db.database import close_db, init_db

# 初始化统一日志（控制台 + 按日期滚动文件 + 敏感信息脱敏）
setup_logging()
logger = logging.getLogger("ragchat")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ===== 启动阶段 =====
    logger.info("=" * 60)
    logger.info("RAG Chat 启动中...")
    logger.info("=" * 60)

    # 1. 数据库迁移（Alembic upgrade head）
    logger.info("数据库准备：执行 Alembic 迁移...")
    await init_db()
    logger.info("数据库准备完成")

    # 2. 回收上次异常中断遗留的评测任务（pending/running → stopped）
    from app.services import ml_service

    recovered = await ml_service.recover_stale_eval_tasks()
    if recovered:
        logger.info("已回收 %d 个遗留的评测任务（标记为已停止）", recovered)

    # 3. 恢复上次异常中断的文档入库任务（解析/切片/向量化中途断开）
    from app.services import ingest

    resumed_docs = await ingest.recover_stale_documents()
    if resumed_docs:
        logger.info("已恢复 %d 个中断的文档入库任务", resumed_docs)

    logger.info("应用启动完成")
    yield

    # ===== 关闭阶段 =====
    logger.info("应用关闭中...")
    await close_db()
    logger.info("应用已关闭")


app = FastAPI(
    title=settings.APP_NAME,
    description="RAG Chat API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
cors_origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
allow_credentials = "*" not in cors_origins
if "*" in cors_origins:
    logger.warning(
        "CORS_ORIGINS 使用通配符 '*'，已关闭 allow_credentials。"
        "生产环境建议配置具体前端域名白名单。"
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 请求日志中间件：记录 method + path + query + status + 耗时
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start_time) * 1000
    response.headers["X-Process-Time"] = f"{duration_ms:.4f}"

    query = str(request.query_params)
    logger.info(
        "%s %s%s - status=%s duration=%.1fms",
        request.method,
        request.url.path,
        f"?{query}" if query else "",
        response.status_code,
        duration_ms,
    )
    return response


# 全局异常处理器
register_exception_handlers(app)

# 业务路由（统一 /api/v1 前缀）
app.include_router(api_router, prefix="/api/v1")


@app.get("/", tags=["Health"])
async def root():
    return {"message": "RAG Chat API"}


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    from logging.handlers import TimedRotatingFileHandler
    from pathlib import Path

    # 将 uvicorn 访问/错误日志输出到 logs/ 目录（按日滚动）
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    class _SimpleFormatter(logging.Formatter):
        def __init__(self):
            super().__init__(
                fmt="%(asctime)s %(levelname)s:  %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )

    _uvicorn_log_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {"()": _SimpleFormatter},
            "access": {"()": _SimpleFormatter},
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "stream": "ext://sys.stderr",
            },
            "console_access": {
                "class": "logging.StreamHandler",
                "formatter": "access",
                "stream": "ext://sys.stderr",
            },
            "file_uvicorn": {
                "class": "logging.handlers.TimedRotatingFileHandler",
                "formatter": "default",
                "filename": str(log_dir / "uvicorn.log"),
                "when": "midnight",
                "interval": 1,
                "backupCount": 30,
                "encoding": "utf-8",
            },
            "file_access": {
                "class": "logging.handlers.TimedRotatingFileHandler",
                "formatter": "access",
                "filename": str(log_dir / "access.log"),
                "when": "midnight",
                "interval": 1,
                "backupCount": 30,
                "encoding": "utf-8",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["console", "file_uvicorn"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"level": "INFO"},
            "uvicorn.access": {"handlers": ["console_access", "file_access"], "level": "INFO", "propagate": False},
        },
    }

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=4040,
        reload=True,
        log_config=_uvicorn_log_config,
    )