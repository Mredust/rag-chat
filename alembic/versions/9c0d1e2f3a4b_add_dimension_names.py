"""add dimension_names snapshot to ml_eval_task and ml_leaderboard

Revision ID: 9c0d1e2f3a4b
Revises: 8b9c0d1e2f3a
Create Date: 2026-09-04 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9c0d1e2f3a4b'
down_revision: Union[str, Sequence[str], None] = '8b9c0d1e2f3a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """为评测任务与排行榜增加维度名称快照列，维度删除后仍可展示名称。"""
    for table in ('ml_eval_task', 'ml_leaderboard'):
        op.add_column(table, sa.Column('dimension_names', sa.JSON(), nullable=True))
        op.execute(f"UPDATE {table} SET dimension_names = JSON_ARRAY() WHERE dimension_names IS NULL")
        op.alter_column(table, 'dimension_names', existing_type=sa.JSON(), nullable=False)


def downgrade() -> None:
    """移除维度名称快照列。"""
    op.drop_column('ml_leaderboard', 'dimension_names')
    op.drop_column('ml_eval_task', 'dimension_names')