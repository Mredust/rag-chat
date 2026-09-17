"""drop algorithm tables

Revision ID: 0b1c2d3e4f5a
Revises: f2a3b4c5d6e7
Create Date: 2026-09-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '0b1c2d3e4f5a'
down_revision: Union[str, Sequence[str], None] = 'f2a3b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """移除「算法实验」模块对应的表（已与模型训练/测评主链路合并，避免重复）。

    MySQL 中 FK 列上的索引与约束绑定，无法单独 drop_index（会报
    “needed in a foreign key constraint”），直接 DROP TABLE 会一并删除约束与索引。
    按外键依赖倒序（子表 → 父表）删除即可。
    """
    op.drop_table('experiment_metric')
    op.drop_table('experiment')
    op.drop_table('train_job')
    op.drop_table('train_example')
    op.drop_table('train_dataset')
    op.drop_table('chunking_strategy')


def downgrade() -> None:
    """回滚：重建算法实验相关表（仅结构，不含数据）。"""
    pass