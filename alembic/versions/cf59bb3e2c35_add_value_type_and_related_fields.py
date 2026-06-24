"""add value_type and related fields

Revision ID: cf59bb3e2c35
Revises: 160a79baf92b
Create Date: 2026-06-17 19:36:32.105151

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cf59bb3e2c35'
down_revision: Union[str, Sequence[str], None] = '160a79baf92b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add new columns
    op.add_column('check_items', sa.Column('value_type', sa.String(length=20), nullable=False, server_default='numeric'))
    op.add_column('check_items', sa.Column('text_value', sa.String(), nullable=True))
    op.add_column('check_items', sa.Column('formula_value', sa.String(), nullable=True))
    op.add_column('check_items', sa.Column('source_block_ids', sa.JSON(), nullable=True))

    op.add_column('source_items', sa.Column('value_type', sa.String(length=20), nullable=False, server_default='numeric'))
    op.add_column('source_items', sa.Column('text_value', sa.String(), nullable=True))
    op.add_column('source_items', sa.Column('formula_value', sa.String(), nullable=True))
    op.add_column('source_items', sa.Column('source_block_ids', sa.JSON(), nullable=True))

    # Alter existing columns to be nullable
    with op.batch_alter_table('check_items', schema=None) as batch_op:
        batch_op.alter_column('value',
               existing_type=sa.FLOAT(),
               nullable=True)
        batch_op.alter_column('unit',
               existing_type=sa.VARCHAR(length=50),
               nullable=True)

    with op.batch_alter_table('source_items', schema=None) as batch_op:
        batch_op.alter_column('value',
               existing_type=sa.FLOAT(),
               nullable=True)
        batch_op.alter_column('unit',
               existing_type=sa.VARCHAR(length=50),
               nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('source_items', schema=None) as batch_op:
        batch_op.alter_column('unit',
               existing_type=sa.VARCHAR(length=50),
               nullable=False)
        batch_op.alter_column('value',
               existing_type=sa.FLOAT(),
               nullable=False)
        batch_op.drop_column('source_block_ids')
        batch_op.drop_column('formula_value')
        batch_op.drop_column('text_value')
        batch_op.drop_column('value_type')

    with op.batch_alter_table('check_items', schema=None) as batch_op:
        batch_op.alter_column('unit',
               existing_type=sa.VARCHAR(length=50),
               nullable=False)
        batch_op.alter_column('value',
               existing_type=sa.FLOAT(),
               nullable=False)
        batch_op.drop_column('source_block_ids')
        batch_op.drop_column('formula_value')
        batch_op.drop_column('text_value')
        batch_op.drop_column('value_type')
