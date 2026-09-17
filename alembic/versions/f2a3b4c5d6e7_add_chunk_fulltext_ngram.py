"""add FULLTEXT ngram index on chunk.content for Chinese search

Revision ID: f2a3b4c5d6e7
Revises: e8f9a0b1c2d3
Create Date: 2026-09-08 17:00:00.000000

为 chunk.content 建立 MySQL ngram 全文索引，使 fulltext_search 的
MATCH ... AGAINST 路径对中文生效，避免静默降级为 LIKE 关键词匹配。

前置条件：MySQL >= 5.7.6（InnoDB 内建 ngram 解析器）；
默认 ngram_token_size=2（二元分词，适合中文）。若需整词分词可设
ngram_token_size=1 或调整，但一般保持默认即可。
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f2a3b4c5d6e7'
down_revision: Union[str, Sequence[str], None] = 'e8f9a0b1c2d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """建立 chunk.content 的 ngram 全文索引。"""
    op.execute(
        "ALTER TABLE chunk ADD FULLTEXT INDEX ft_chunk_content (content) WITH PARSER ngram"
    )


def downgrade() -> None:
    """移除 chunk.content 的 ngram 全文索引。"""
    op.execute("ALTER TABLE chunk DROP INDEX ft_chunk_content")