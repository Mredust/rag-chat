"""add microsecond precision to chat_messages.created_at

Revision ID: d0e1f2a3b4c5
Revises: 9c0d1e2f3a4b
Create Date: 2026-09-04 23:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


# revision identifiers, used by Alembic.
revision: str = 'd0e1f2a3b4c5'
down_revision: Union[str, Sequence[str], None] = '9c0d1e2f3a4b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """将 chat_messages.created_at 升级为 DATETIME(6)，并去掉秒级 server_default。"""
    op.alter_column(
        'chat_messages',
        'created_at',
        existing_type=mysql.DATETIME(),
        type_=mysql.DATETIME(fsp=6),
        existing_nullable=False,
        existing_server_default=sa.text('CURRENT_TIMESTAMP'),
        server_default=None,
    )


def downgrade() -> None:
    """回退为秒级 DATETIME + CURRENT_TIMESTAMP。"""
    op.alter_column(
        'chat_messages',
        'created_at',
        existing_type=mysql.DATETIME(fsp=6),
        type_=mysql.DATETIME(),
        existing_nullable=False,
        server_default=sa.text('CURRENT_TIMESTAMP'),
    )