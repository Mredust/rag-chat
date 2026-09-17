"""add provider_config and drop deploy_methods on ml_model

Revision ID: e8f9a0b1c2d3
Revises: a2b3c4d5e6f7
Create Date: 2026-09-07 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8f9a0b1c2d3'
down_revision: Union[str, Sequence[str], None] = 'a2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """模型：移除支持部署方式列，新增供应商向量模型配置列。"""
    op.drop_column('ml_model', 'deploy_methods')
    op.add_column(
        'ml_model',
        sa.Column('provider_config', sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    """回滚：移除供应商配置列，恢复支持部署方式列。"""
    op.drop_column('ml_model', 'provider_config')
    op.add_column(
        'ml_model',
        sa.Column('deploy_methods', sa.JSON(), nullable=True),
    )