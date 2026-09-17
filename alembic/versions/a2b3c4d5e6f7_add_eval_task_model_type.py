"""add model_type and llm_model_id to ml_eval_task

Revision ID: a2b3c4d5e6f7
Revises: b0c1d2e3f4a5
Create Date: 2026-09-07 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a2b3c4d5e6f7'
down_revision: Union[str, Sequence[str], None] = 'b0c1d2e3f4a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """为评测任务增加评测模型类型与供应商模型 ID 列。"""
    op.add_column(
        'ml_eval_task',
        sa.Column('model_type', sa.String(length=16), nullable=False, server_default='vector'),
    )
    op.add_column(
        'ml_eval_task',
        sa.Column('llm_model_id', sa.String(length=40), nullable=True),
    )


def downgrade() -> None:
    """移除评测模型类型与供应商模型 ID 列。"""
    op.drop_column('ml_eval_task', 'llm_model_id')
    op.drop_column('ml_eval_task', 'model_type')