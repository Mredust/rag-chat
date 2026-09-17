"""add provider.model_names and eval task auto-split fields

Revision ID: a7b8c9d0e1f2
Revises: 0b1c2d3e4f5a
Create Date: 2026-09-09 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = '0b1c2d3e4f5a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """供应商新增 model_names 列表；评测任务新增自动切分配置。"""
    # provider.model_names（多模型兜底列表，JSON）
    op.add_column('provider', sa.Column('model_names', sa.JSON(), nullable=True))
    op.execute("UPDATE provider SET model_names = JSON_ARRAY() WHERE model_names IS NULL")
    op.alter_column('provider', 'model_names', existing_type=sa.JSON(), nullable=False)

    # ml_eval_task 评测数据来源方式：dataset（选择测评集）/ auto_split（自动切分）
    op.add_column('ml_eval_task', sa.Column('data_mode', sa.String(length=16), nullable=False, server_default='dataset'))
    # 自动切分使用的训练集 ID
    op.add_column('ml_eval_task', sa.Column('split_dataset_id', sa.String(length=40), nullable=False, server_default=''))
    # 自动切分比例（默认 10%）
    op.add_column('ml_eval_task', sa.Column('split_ratio', sa.Float(), nullable=False, server_default='0.1'))


def downgrade() -> None:
    """回滚：移除新增字段。"""
    op.drop_column('ml_eval_task', 'split_ratio')
    op.drop_column('ml_eval_task', 'split_dataset_id')
    op.drop_column('ml_eval_task', 'data_mode')
    op.drop_column('provider', 'model_names')