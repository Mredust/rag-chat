"""switch eval task / leaderboard from single dimension to multiple dimensions

Revision ID: 7a8b9c0d1e2f
Revises: 6f7a8b9c0d1e
Create Date: 2026-09-04 21:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7a8b9c0d1e2f'
down_revision: Union[str, Sequence[str], None] = '6f7a8b9c0d1e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _fk_name(bind, table: str, column: str) -> str | None:
    """按列动态查找外键约束名（初始建表外键未显式命名，MySQL 自动生成）。"""
    row = bind.execute(
        sa.text(
            "SELECT CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND COLUMN_NAME = :c "
            "AND REFERENCED_TABLE_NAME IS NOT NULL"
        ),
        {"t": table, "c": column},
    ).fetchone()
    return row[0] if row else None


def _replace_dimension_id_with_list(table: str, index_name: str) -> None:
    """单维度字段迁移为多维度 JSON 字段，并清理旧字段。"""
    bind = op.get_bind()
    # 1) 新增 JSON 列表字段
    op.add_column(table, sa.Column('dimension_ids', sa.JSON(), nullable=True))
    # 2) 回填：旧的 dimension_id 单值 → 单元素数组
    op.execute(f"UPDATE {table} SET dimension_ids = JSON_ARRAY(dimension_id) WHERE dimension_id IS NOT NULL")
    op.execute(f"UPDATE {table} SET dimension_ids = JSON_ARRAY() WHERE dimension_ids IS NULL")
    op.alter_column(table, 'dimension_ids', existing_type=sa.JSON(), nullable=False)
    # 3) 移除旧字段及其外键与索引
    fk = _fk_name(bind, table, 'dimension_id')
    if fk:
        op.drop_constraint(fk, table, type_='foreignkey')
    op.drop_index(op.f(index_name), table_name=table)
    op.drop_column(table, 'dimension_id')


def upgrade() -> None:
    """将评测任务与排行榜的评测维度由单值改为多值列表。"""
    _replace_dimension_id_with_list('ml_eval_task', 'ix_ml_eval_task_dimension_id')
    _replace_dimension_id_with_list('ml_leaderboard', 'ix_ml_leaderboard_dimension_id')


def downgrade() -> None:
    """回滚为单维度字段。"""
    # ml_eval_task
    op.add_column('ml_eval_task', sa.Column('dimension_id', sa.String(length=40), nullable=True))
    op.execute("UPDATE ml_eval_task SET dimension_id = JSON_UNQUOTE(JSON_EXTRACT(dimension_ids, '$[0]')) WHERE JSON_LENGTH(dimension_ids) > 0")
    op.create_index(op.f('ix_ml_eval_task_dimension_id'), 'ml_eval_task', ['dimension_id'], unique=False)
    op.create_foreign_key('fk_ml_eval_task_dimension_id', 'ml_eval_task', 'ml_eval_dimension', ['dimension_id'], ['id'], ondelete='SET NULL')
    op.drop_column('ml_eval_task', 'dimension_ids')

    # ml_leaderboard
    op.add_column('ml_leaderboard', sa.Column('dimension_id', sa.String(length=40), nullable=True))
    op.execute("UPDATE ml_leaderboard SET dimension_id = JSON_UNQUOTE(JSON_EXTRACT(dimension_ids, '$[0]')) WHERE JSON_LENGTH(dimension_ids) > 0")
    op.create_index(op.f('ix_ml_leaderboard_dimension_id'), 'ml_leaderboard', ['dimension_id'], unique=False)
    op.create_foreign_key('fk_ml_leaderboard_dimension_id', 'ml_leaderboard', 'ml_eval_dimension', ['dimension_id'], ['id'], ondelete='SET NULL')
    op.drop_column('ml_leaderboard', 'dimension_ids')