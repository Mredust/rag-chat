"""drop metrics column from ml_eval_dimension

Revision ID: 5e6f7a8b9c0d
Revises: 4d5e6f7a8b9c
Create Date: 2026-09-04 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5e6f7a8b9c0d'
down_revision: Union[str, Sequence[str], None] = '4d5e6f7a8b9c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """移除评测维度的指标列。"""
    op.drop_column('ml_eval_dimension', 'metrics')


def downgrade() -> None:
    """恢复评测维度的指标列。"""
    op.add_column('ml_eval_dimension', sa.Column('metrics', sa.JSON(), nullable=False))