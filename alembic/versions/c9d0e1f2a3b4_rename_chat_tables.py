"""rename chat tables

Revision ID: c9d0e1f2a3b4
Revises: a3b4c5d6e7f8
Create Date: 2026-08-31 23:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c9d0e1f2a3b4'
down_revision: Union[str, Sequence[str], None] = 'a3b4c5d6e7f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """将 conversation/message 表重命名为 chat_sessions/chat_messages。"""
    op.rename_table('conversation', 'chat_sessions')
    op.rename_table('message', 'chat_messages')


def downgrade() -> None:
    """回退表名。"""
    op.rename_table('chat_messages', 'message')
    op.rename_table('chat_sessions', 'conversation')