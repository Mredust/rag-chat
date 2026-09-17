"""switch chat_messages.id to auto-increment integer

Revision ID: e0f1a2b3c4d5
Revises: d0e1f2a3b4c5
Create Date: 2026-09-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e0f1a2b3c4d5'
down_revision: Union[str, Sequence[str], None] = 'd0e1f2a3b4c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """将 chat_messages.id 由随机 UUID 字符串改为自增整数主键。

    原 id 为随机 UUID，无递增关系，配合秒级 created_at 会导致同秒消息乱序。
    改为自增整数后按 id 单调排序即可稳定还原用户/助手的先后顺序。
    """
    op.execute("ALTER TABLE chat_messages DROP PRIMARY KEY")
    op.execute("ALTER TABLE chat_messages DROP COLUMN id")
    op.execute(
        "ALTER TABLE chat_messages "
        "ADD COLUMN id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY FIRST"
    )


def downgrade() -> None:
    """回退为字符串主键（自增整数 id 转为字符串，历史顺序需重新依赖 created_at）。"""
    op.execute("ALTER TABLE chat_messages DROP PRIMARY KEY")
    op.execute("ALTER TABLE chat_messages MODIFY COLUMN id VARCHAR(40) NOT NULL")
    op.execute("ALTER TABLE chat_messages ADD PRIMARY KEY (id)")