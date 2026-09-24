"""convert absolute paths to project-relative in path columns

Revision ID: c1d2e3f4a5b6
Revises: a7b8c9d0e1f2
Create Date: 2026-09-23 15:00:00.000000

"""
import os
from pathlib import Path
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, Sequence[str], None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 项目根目录（rag-chat）：alembic/versions/xxx.py → parents[2]
BASE_DIR = Path(__file__).resolve().parents[2]


def _to_rel(value: str) -> str:
    """绝对路径转为项目根目录下的相对路径（前带分隔符）；非项目内路径原样返回。"""
    if not value:
        return value
    try:
        p = Path(value)
        if not p.is_absolute():
            return value
        rel = p.resolve().relative_to(BASE_DIR.resolve())
        return os.sep + str(rel)
    except (ValueError, OSError):
        return value


def _to_rel_multi(value: str) -> str:
    """逗号分隔的多路径字段（ml_dataset_version.storage_path）逐项转换。"""
    if not value:
        return value
    return ",".join(_to_rel(part.strip()) for part in value.split(","))


def upgrade() -> None:
    """存量绝对路径改为相对路径：document / ml_dataset_version / ml_train_task / system_config。"""
    conn = op.get_bind()

    # 1. 知识库文档 storage_path
    rows = conn.execute(sa.text("SELECT id, storage_path FROM document")).fetchall()
    for row in rows:
        new_val = _to_rel(row.storage_path or "")
        if new_val != (row.storage_path or ""):
            conn.execute(
                sa.text("UPDATE document SET storage_path = :p WHERE id = :id"),
                {"p": new_val, "id": row.id},
            )

    # 2. 数据集版本 storage_path（可能逗号分隔多文件）
    rows = conn.execute(
        sa.text("SELECT id, storage_path FROM ml_dataset_version")
    ).fetchall()
    for row in rows:
        new_val = _to_rel_multi(row.storage_path or "")
        if new_val != (row.storage_path or ""):
            conn.execute(
                sa.text("UPDATE ml_dataset_version SET storage_path = :p WHERE id = :id"),
                {"p": new_val, "id": row.id},
            )

    # 3. 训练任务 output_dir
    rows = conn.execute(sa.text("SELECT id, output_dir FROM ml_train_task")).fetchall()
    for row in rows:
        new_val = _to_rel(row.output_dir or "")
        if new_val != (row.output_dir or ""):
            conn.execute(
                sa.text("UPDATE ml_train_task SET output_dir = :p WHERE id = :id"),
                {"p": new_val, "id": row.id},
            )

    # 4. 系统配置 rerank_model（非敏感明文；`key` 为 MySQL 保留字需反引号）
    row = conn.execute(
        sa.text("SELECT value FROM system_config WHERE `key` = 'rerank_model'")
    ).first()
    if row is not None:
        new_val = _to_rel(row.value or "")
        if new_val != (row.value or ""):
            conn.execute(
                sa.text("UPDATE system_config SET value = :p WHERE `key` = 'rerank_model'"),
                {"p": new_val},
            )


def downgrade() -> None:
    """相对路径无法可靠还原为绝对路径（依赖部署环境），不做回滚。"""
