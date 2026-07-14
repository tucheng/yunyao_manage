"""Create the current application schema.

Revision ID: 0001_initial_schema
Revises:
"""

from alembic import op

from database import Base
import models  # noqa: F401


revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind(), checkfirst=True)
