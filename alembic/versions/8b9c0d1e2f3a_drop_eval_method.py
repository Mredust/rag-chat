"""drop eval_method from ml_eval_task

Revision ID: 8b9c0d1e2f3a
Revises: 7a8b9c0d1e2f
Create Date: 2026-09-04 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8b9c0d1e2f3a'
down_revision: Union[str, Sequence[str], None] = '7a8b9c0d1e2f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """移除评测任务列表中的「评测方式」字段。"""
    op.drop_column('ml_eval_task', 'eval_method')


def downgrade() -> None:
    """恢复「评测方式」字段。"""
    op.add_column(
        'ml_eval_task',
        sa.Column('eval_method', sa.String(length=16), nullable=False, server_default='custom'),
    )