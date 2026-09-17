"""add metrics column to ml_train_task

Revision ID: b0c1d2e3f4a5
Revises: e0f1a2b3c4d5
Create Date: 2026-09-05 23:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b0c1d2e3f4a5'
down_revision: Union[str, Sequence[str], None] = 'e0f1a2b3c4d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """为训练任务新增指标列（JSON），存量行默认空对象。"""
    op.add_column(
        'ml_train_task',
        sa.Column(
            'metrics',
            sa.JSON(),
            nullable=False,
            server_default=sa.text("(JSON_OBJECT())"),
        ),
    )


def downgrade() -> None:
    """移除训练任务指标列。"""
    op.drop_column('ml_train_task', 'metrics')