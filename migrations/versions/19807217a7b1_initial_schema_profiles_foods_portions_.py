"""Initial schema: profiles, foods, portions, meal drafts, consumption entries, commands

Revision ID: 19807217a7b1
Revises: 
Create Date: 2026-08-16 14:37:49.594262

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '19807217a7b1'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    from snack_gpt.db import Base
    import snack_gpt.models.domain

    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    """Downgrade schema."""
    from snack_gpt.db import Base
    import snack_gpt.models.domain

    Base.metadata.drop_all(bind=op.get_bind())
