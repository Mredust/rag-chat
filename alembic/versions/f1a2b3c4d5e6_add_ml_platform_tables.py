"""add ml platform tables

Revision ID: f1a2b3c4d5e6
Revises: e5b6c7d8a9f0
Create Date: 2026-09-03 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'e5b6c7d8a9f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('ml_dataset',
        sa.Column('id', sa.String(length=40), nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('dataset_type', sa.String(length=16), nullable=False),
        sa.Column('train_scene', sa.String(length=32), nullable=True),
        sa.Column('train_method', sa.String(length=16), nullable=True),
        sa.Column('storage_location', sa.String(length=16), nullable=False),
        sa.Column('import_method', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table('ml_dataset_version',
        sa.Column('id', sa.String(length=40), nullable=False),
        sa.Column('dataset_id', sa.String(length=40), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('file_count', sa.Integer(), nullable=False),
        sa.Column('data_count', sa.Integer(), nullable=False),
        sa.Column('import_status', sa.String(length=16), nullable=False),
        sa.Column('publish_status', sa.String(length=16), nullable=False),
        sa.Column('file_id', sa.String(length=64), nullable=False),
        sa.Column('storage_path', sa.String(length=512), nullable=False),
        sa.Column('preview_content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['dataset_id'], ['ml_dataset.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ml_dataset_version_dataset_id'), 'ml_dataset_version', ['dataset_id'], unique=False)

    op.create_table('ml_model',
        sa.Column('id', sa.String(length=40), nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('base_model', sa.String(length=128), nullable=False),
        sa.Column('train_method', sa.String(length=16), nullable=False),
        sa.Column('source', sa.String(length=16), nullable=False),
        sa.Column('bucket', sa.String(length=128), nullable=False),
        sa.Column('model_dir', sa.String(length=512), nullable=False),
        sa.Column('deploy_methods', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table('ml_train_task',
        sa.Column('id', sa.String(length=40), nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('priority', sa.String(length=4), nullable=False),
        sa.Column('train_method', sa.String(length=16), nullable=False),
        sa.Column('base_model', sa.String(length=128), nullable=False),
        sa.Column('dataset_id', sa.String(length=40), nullable=True),
        sa.Column('valid_ratio', sa.Float(), nullable=False),
        sa.Column('config', sa.JSON(), nullable=False),
        sa.Column('output_model_name', sa.String(length=128), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('output_dir', sa.String(length=512), nullable=False),
        sa.Column('log', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['dataset_id'], ['ml_dataset.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ml_train_task_dataset_id'), 'ml_train_task', ['dataset_id'], unique=False)
    op.create_index(op.f('ix_ml_train_task_status'), 'ml_train_task', ['status'], unique=False)

    op.create_table('ml_eval_dimension',
        sa.Column('id', sa.String(length=40), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('metrics', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table('ml_eval_task',
        sa.Column('id', sa.String(length=40), nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('eval_method', sa.String(length=16), nullable=False),
        sa.Column('model_id', sa.String(length=40), nullable=True),
        sa.Column('data_source', sa.String(length=16), nullable=False),
        sa.Column('data_id', sa.String(length=40), nullable=False),
        sa.Column('dimension_id', sa.String(length=40), nullable=True),
        sa.Column('sync_leaderboard', sa.Boolean(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('result', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['model_id'], ['ml_model.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['dimension_id'], ['ml_eval_dimension.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ml_eval_task_model_id'), 'ml_eval_task', ['model_id'], unique=False)
    op.create_index(op.f('ix_ml_eval_task_dimension_id'), 'ml_eval_task', ['dimension_id'], unique=False)
    op.create_index(op.f('ix_ml_eval_task_status'), 'ml_eval_task', ['status'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_ml_eval_task_status'), table_name='ml_eval_task')
    op.drop_index(op.f('ix_ml_eval_task_dimension_id'), table_name='ml_eval_task')
    op.drop_index(op.f('ix_ml_eval_task_model_id'), table_name='ml_eval_task')
    op.drop_table('ml_eval_task')
    op.drop_table('ml_eval_dimension')
    op.drop_index(op.f('ix_ml_train_task_status'), table_name='ml_train_task')
    op.drop_index(op.f('ix_ml_train_task_dataset_id'), table_name='ml_train_task')
    op.drop_table('ml_train_task')
    op.drop_table('ml_model')
    op.drop_index(op.f('ix_ml_dataset_version_dataset_id'), table_name='ml_dataset_version')
    op.drop_table('ml_dataset_version')
    op.drop_table('ml_dataset')