"""add file_hash to source_documents

Revision ID: 8f35814e860f
Revises: 22f526ae4fda
Create Date: 2026-06-13 07:23:38.972863

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8f35814e860f'
down_revision: Union[str, Sequence[str], None] = '22f526ae4fda'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('source_documents', sa.Column('file_hash', sa.String(length=64), nullable=True))
    op.create_index('ix_source_documents_file_hash', 'source_documents', ['file_hash'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_source_documents_file_hash', table_name='source_documents')
    op.drop_column('source_documents', 'file_hash')
