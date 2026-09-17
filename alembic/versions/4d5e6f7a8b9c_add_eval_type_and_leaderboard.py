"""add eval_type/eval_config to dimension, task counters, and leaderboard table

Revision ID: 4d5e6f7a8b9c
Revises: a1b2c3d4e5f6
Create Date: 2026-09-04 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4d5e6f7a8b9c'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """为评测维度补充类型与配置、为评测任务补充计数，并新增排行榜表。"""
    # 1) ml_eval_dimension：新增 eval_type / eval_config（先可空，回填后收紧）
    op.add_column('ml_eval_dimension', sa.Column('eval_type', sa.String(length=32), nullable=True))
    op.add_column('ml_eval_dimension', sa.Column('eval_config', sa.JSON(), nullable=True))
    op.execute("UPDATE ml_eval_dimension SET eval_type = 'llm_classify' WHERE eval_type IS NULL")
    op.execute("UPDATE ml_eval_dimension SET eval_config = JSON_OBJECT() WHERE eval_config IS NULL")
    op.alter_column('ml_eval_dimension', 'eval_type', existing_type=sa.String(length=32), nullable=False)
    op.alter_column('ml_eval_dimension', 'eval_config', existing_type=sa.JSON(), nullable=False)

    # 2) ml_eval_task：新增 total_count / completed_count
    op.add_column('ml_eval_task', sa.Column('total_count', sa.Integer(), nullable=True))
    op.add_column('ml_eval_task', sa.Column('completed_count', sa.Integer(), nullable=True))
    op.execute("UPDATE ml_eval_task SET total_count = 0 WHERE total_count IS NULL")
    op.execute("UPDATE ml_eval_task SET completed_count = 0 WHERE completed_count IS NULL")
    op.alter_column('ml_eval_task', 'total_count', existing_type=sa.Integer(), nullable=False)
    op.alter_column('ml_eval_task', 'completed_count', existing_type=sa.Integer(), nullable=False)

    # 3) ml_leaderboard：排行榜表
    op.create_table(
        'ml_leaderboard',
        sa.Column('id', sa.String(length=40), nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('dimension_id', sa.String(length=40), nullable=True),
        sa.Column('task_ids', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['dimension_id'], ['ml_eval_dimension.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_ml_leaderboard_dimension_id'), 'ml_leaderboard', ['dimension_id'], unique=False)


def downgrade() -> None:
    """回滚：删除排行榜表，移除新增列。"""
    op.drop_index(op.f('ix_ml_leaderboard_dimension_id'), table_name='ml_leaderboard')
    op.drop_table('ml_leaderboard')

    op.drop_column('ml_eval_task', 'completed_count')
    op.drop_column('ml_eval_task', 'total_count')

    op.drop_column('ml_eval_dimension', 'eval_config')
    op.drop_column('ml_eval_dimension', 'eval_type')