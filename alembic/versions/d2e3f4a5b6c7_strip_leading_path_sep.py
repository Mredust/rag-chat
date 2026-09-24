"""strip leading separators from project-relative path columns

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-09-24 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2e3f4a5b6c7'
down_revision: Union[str, Sequence[str], None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _normalize(value: str) -> str:
    """存量相对路径去掉前导 ``\\`` / ``/``，并统一为正斜杠（不含盘符）。"""
    if not value:
        return value
    s = value.strip()
    # 仅处理相对路径（不触碰盘符开头的绝对路径）
    if len(s) >= 2 and s[1] == ":":
        return value
    s = s.lstrip("\\/")
    return s.replace("\\", "/")


def _normalize_multi(value: str) -> str:
    """逗号分隔的多路径字段逐项转换。"""
    if not value:
        return value
    return ",".join(_normalize(part.strip()) for part in value.split(","))


def upgrade() -> None:
    conn = op.get_bind()

    rows = conn.execute(sa.text("SELECT id, storage_path FROM document")).fetchall()
    for row in rows:
        new_val = _normalize(row.storage_path or "")
        if new_val != (row.storage_path or ""):
            conn.execute(
                sa.text("UPDATE document SET storage_path = :p WHERE id = :id"),
                {"p": new_val, "id": row.id},
            )

    rows = conn.execute(
        sa.text("SELECT id, storage_path FROM ml_dataset_version")
    ).fetchall()
    for row in rows:
        new_val = _normalize_multi(row.storage_path or "")
        if new_val != (row.storage_path or ""):
            conn.execute(
                sa.text("UPDATE ml_dataset_version SET storage_path = :p WHERE id = :id"),
                {"p": new_val, "id": row.id},
            )

    rows = conn.execute(sa.text("SELECT id, output_dir FROM ml_train_task")).fetchall()
    for row in rows:
        new_val = _normalize(row.output_dir or "")
        if new_val != (row.output_dir or ""):
            conn.execute(
                sa.text("UPDATE ml_train_task SET output_dir = :p WHERE id = :id"),
                {"p": new_val, "id": row.id},
            )

    # 模型目录
    rows = conn.execute(sa.text("SELECT id, model_dir FROM ml_model")).fetchall()
    for row in rows:
        new_val = _normalize(row.model_dir or "")
        if new_val != (row.model_dir or ""):
            conn.execute(
                sa.text("UPDATE ml_model SET model_dir = :p WHERE id = :id"),
                {"p": new_val, "id": row.id},
            )

    row = conn.execute(
        sa.text("SELECT value FROM system_config WHERE `key` = 'rerank_model'")
    ).first()
    if row is not None:
        new_val = _normalize(row.value or "")
        if new_val != (row.value or ""):
            conn.execute(
                sa.text("UPDATE system_config SET value = :p WHERE `key` = 'rerank_model'"),
                {"p": new_val},
            )


def downgrade() -> None:
    """相对路径无法可靠还原为带前导分隔符的形态，不做回滚。"""
