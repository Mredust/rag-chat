"""add_provider

Revision ID: a3b4c5d6e7f8
Revises: b838d9b27294
Create Date: 2026-08-31 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3b4c5d6e7f8'
down_revision: Union[str, Sequence[str], None] = 'b838d9b27294'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('provider',
        sa.Column('id', sa.String(length=40), nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('api_type', sa.String(length=16), nullable=False),
        sa.Column('api_base', sa.String(length=500), nullable=False),
        sa.Column('api_key', sa.Text(), nullable=False),
        sa.Column('model_name', sa.String(length=128), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('provider')