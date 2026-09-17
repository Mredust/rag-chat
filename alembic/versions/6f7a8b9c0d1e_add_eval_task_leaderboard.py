"""add leaderboard_id to ml_eval_task

Revision ID: 6f7a8b9c0d1e
Revises: 5e6f7a8b9c0d
Create Date: 2026-09-04 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6f7a8b9c0d1e'
down_revision: Union[str, Sequence[str], None] = '5e6f7a8b9c0d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """为评测任务新增同步目标排行榜字段。"""
    op.add_column('ml_eval_task', sa.Column('leaderboard_id', sa.String(length=40), nullable=True))
    op.create_index(op.f('ix_ml_eval_task_leaderboard_id'), 'ml_eval_task', ['leaderboard_id'], unique=False)
    op.create_foreign_key(
        'fk_ml_eval_task_leaderboard_id',
        'ml_eval_task',
        'ml_leaderboard',
        ['leaderboard_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    """移除评测任务的同步目标排行榜字段。"""
    op.drop_constraint('fk_ml_eval_task_leaderboard_id', 'ml_eval_task', type_='foreignkey')
    op.drop_index(op.f('ix_ml_eval_task_leaderboard_id'), table_name='ml_eval_task')
    op.drop_column('ml_eval_task', 'leaderboard_id')