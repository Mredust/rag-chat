"""应用级配置：全部通过环境变量 / .env 注入。"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（rag-chat），.env 文件位于该目录下
BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- 应用 ----
    APP_NAME: str = "rag-chat"
    DEBUG: bool = True
    LOG_LEVEL: str = "DEBUG"

    # ---- 数据库（MySQL）----
    MYSQL_HOST: str = "localhost"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "root"
    MYSQL_PASSWORD: str = "mredust4"
    MYSQL_DB: str = "ragchat"

    # ---- 向量数据库（Chroma）----
    CHROMA_PERSIST_DIR: str = "./data/chroma"
    CHROMA_COLLECTION: str = "knowledge_chunks"

    # ---- 大模型（LLM，OpenAI 兼容）----
    LLM_API_BASE: str = "https://api.deepseek.com"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "deepseek-chat"

    # ---- Embedding（OpenAI 兼容 / 本地）----
    EMBEDDING_API_BASE: str = ""
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_MODEL: str = "bge-large-zh-v1.5"
    EMBEDDING_DIM: int = 1024

    # ---- 认证（JWT）----
    JWT_SECRET: str = "rag-chat-dev-secret-change-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # ---- CORS ----
    CORS_ORIGINS: str = "*"

    @property
    def database_url(self) -> str:
        """异步连接串（asyncmy）。"""
        return (
            f"mysql+asyncmy://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DB}?charset=utf8mb4"
        )

    @property
    def sync_database_url(self) -> str:
        """同步连接串（pymysql，Alembic 等使用）。"""
        return (
            f"mysql+pymysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DB}?charset=utf8mb4"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()