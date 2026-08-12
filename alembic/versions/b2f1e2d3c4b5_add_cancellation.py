"""add cancellation

Revision ID: b2f1e2d3c4b5
Revises: 7970795bf3f7
Create Date: 2026-05-16 18:50:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b2f1e2d3c4b5'
down_revision: Union[str, Sequence[str], None] = '7970795bf3f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # 1. Add cancel_requested column
    op.add_column('tasks', sa.Column('cancel_requested', sa.Boolean(), server_default='false', nullable=False))
    
    # 2. Update status enum constraint (native_enum=False means it's a CheckConstraint)
    # Since we are using native_enum=False, we just need to make sure the check constraint is updated if we were strict.
    # But many DBs just store the string.
    pass

def downgrade() -> None:
    op.drop_column('tasks', 'cancel_requested')
