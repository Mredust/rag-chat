"""日志配置模块（参考 rag-learn 项目）。

提供两种日志格式：
- text（开发，默认）：可读的纯文本格式，输出到控制台
- json（生产）：JSON 结构化日志

敏感信息（password、token、Authorization、api_key 等）自动脱敏。
通过环境变量 LOG_FORMAT / LOG_LEVEL 控制，日志同时输出到控制台与按日期滚动的文件。
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

# 敏感字段正则：匹配 password/token/authorization/secret/api_key 的值
_SENSITIVE_PATTERNS = re.compile(
    r'((?:password|token|authorization|secret|api_key)["\s:=]+)["\']?[^"\',\s}]+["\']?',
    re.IGNORECASE,
)


class SensitiveFilter:
    """日志过滤器：自动将敏感字段值替换为 ***"""

    @staticmethod
    def filter(message: str) -> str:
        return _SENSITIVE_PATTERNS.sub(r'\1"***"', str(message))


class TextFormatter(logging.Formatter):
    """纯文本格式化器：时间 级别 [模块:行号] 消息"""

    def __init__(self, datefmt: str = "%Y-%m-%d %H:%M:%S"):
        super().__init__(datefmt=datefmt)

    def format(self, record: logging.LogRecord) -> str:
        message = SensitiveFilter.filter(record.getMessage())
        timestamp = self.formatTime(record, self.datefmt)
        location = f"{record.module}:{record.lineno}"
        return f"{timestamp} {record.levelname:<5} [{location:<24}] {message}"


class JsonFormatter(logging.Formatter):
    """JSON 结构化格式化器：便于日志采集系统解析"""

    def __init__(self, datefmt: str = "%Y-%m-%d %H:%M:%S"):
        super().__init__(datefmt=datefmt)

    def format(self, record: logging.LogRecord) -> str:
        message = SensitiveFilter.filter(record.getMessage())
        entry = {
            "timestamp": datetime.fromtimestamp(record.created).strftime(self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "message": message,
        }
        if hasattr(record, "extra_data"):
            entry["extra"] = record.extra_data
        return json.dumps(entry, ensure_ascii=False)


def setup_logging() -> None:
    """配置根日志记录器，所有模块的 logging.getLogger() 均继承此配置。

    - LOG_FORMAT: "text"（默认）或 "json"
    - LOG_LEVEL: DEBUG（默认）/ INFO / WARNING / ERROR
    """
    root = logging.getLogger()
    if getattr(root, "_rag_chat_configured", False):
        return
    root._rag_chat_configured = True

    # 优先从应用配置读取日志级别（.env 由 pydantic-settings 加载，os.getenv 无法读取）
    try:
        from app.core.config import settings as _settings

        log_level_name = str(getattr(_settings, "LOG_LEVEL", None) or os.getenv("LOG_LEVEL", "DEBUG"))
    except Exception:  # noqa: BLE001
        log_level_name = os.getenv("LOG_LEVEL", "DEBUG")
    level = getattr(logging, log_level_name.upper(), logging.DEBUG)
    root.setLevel(level)

    # 降噪：httpx/httpcore 会打印底层 HTTP 请求日志，改为 WARNING，请求详情由业务层记录
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    log_format = os.getenv("LOG_FORMAT", "text").lower()
    formatter: logging.Formatter = JsonFormatter() if log_format == "json" else TextFormatter()

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    log_dir = Path(__file__).resolve().parent.parent.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = TimedRotatingFileHandler(
        filename=log_dir / "app.log",
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.suffix = "%Y%m%d"
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)