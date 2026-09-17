"""add algorithm tables

Revision ID: e5b6c7d8a9f0
Revises: c9d0e1f2a3b4
Create Date: 2026-09-01 23:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5b6c7d8a9f0'
down_revision: Union[str, Sequence[str], None] = 'c9d0e1f2a3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('chunking_strategy',
        sa.Column('id', sa.String(length=40), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('file_types', sa.JSON(), nullable=False),
        sa.Column('min_len', sa.Integer(), nullable=True),
        sa.Column('max_len', sa.Integer(), nullable=True),
        sa.Column('chunk_size', sa.Integer(), nullable=False),
        sa.Column('chunk_overlap', sa.Integer(), nullable=False),
        sa.Column('overlap_mode', sa.String(length=16), nullable=False),
        sa.Column('separators', sa.JSON(), nullable=True),
        sa.Column('min_chunk_size', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table('train_dataset',
        sa.Column('id', sa.String(length=40), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('space_id', sa.String(length=40), nullable=True),
        sa.Column('base_model', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('stats', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_train_dataset_space_id'), 'train_dataset', ['space_id'], unique=False)

    op.create_table('train_example',
        sa.Column('id', sa.String(length=40), nullable=False),
        sa.Column('dataset_id', sa.String(length=40), nullable=False),
        sa.Column('query', sa.Text(), nullable=False),
        sa.Column('positive_chunk_id', sa.String(length=40), nullable=False),
        sa.Column('negative_chunk_ids', sa.JSON(), nullable=False),
        sa.Column('hard_negative_ids', sa.JSON(), nullable=False),
        sa.Column('label_status', sa.String(length=16), nullable=False),
        sa.Column('source', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['dataset_id'], ['train_dataset.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_train_example_dataset_id'), 'train_example', ['dataset_id'], unique=False)

    op.create_table('train_job',
        sa.Column('id', sa.String(length=40), nullable=False),
        sa.Column('dataset_id', sa.String(length=40), nullable=False),
        sa.Column('base_model', sa.String(length=64), nullable=False),
        sa.Column('params', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('metrics', sa.JSON(), nullable=False),
        sa.Column('output_dir', sa.String(length=512), nullable=False),
        sa.Column('log', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['dataset_id'], ['train_dataset.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_train_job_dataset_id'), 'train_job', ['dataset_id'], unique=False)
    op.create_index(op.f('ix_train_job_status'), 'train_job', ['status'], unique=False)

    op.create_table('experiment',
        sa.Column('id', sa.String(length=40), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('exp_type', sa.String(length=32), nullable=False),
        sa.Column('config', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_experiment_status'), 'experiment', ['status'], unique=False)

    op.create_table('experiment_metric',
        sa.Column('id', sa.String(length=40), nullable=False),
        sa.Column('experiment_id', sa.String(length=40), nullable=False),
        sa.Column('group_name', sa.String(length=64), nullable=False),
        sa.Column('metric_name', sa.String(length=64), nullable=False),
        sa.Column('metric_value', sa.Float(), nullable=False),
        sa.Column('detail', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['experiment_id'], ['experiment.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_experiment_metric_experiment_id'), 'experiment_metric', ['experiment_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_experiment_metric_experiment_id'), table_name='experiment_metric')
    op.drop_table('experiment_metric')
    op.drop_index(op.f('ix_experiment_status'), table_name='experiment')
    op.drop_table('experiment')
    op.drop_index(op.f('ix_train_job_status'), table_name='train_job')
    op.drop_index(op.f('ix_train_job_dataset_id'), table_name='train_job')
    op.drop_table('train_job')
    op.drop_index(op.f('ix_train_example_dataset_id'), table_name='train_example')
    op.drop_table('train_example')
    op.drop_index(op.f('ix_train_dataset_space_id'), table_name='train_dataset')
    op.drop_table('train_dataset')
    op.drop_table('chunking_strategy')