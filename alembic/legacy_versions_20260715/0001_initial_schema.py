"""Create the frozen application schema baseline.

Revision ID: 0001_initial_schema
Revises:
"""

from schema_0001_snapshot import downgrade as drop_baseline_schema
from schema_0001_snapshot import upgrade as create_baseline_schema


revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep revision 0001 immutable.  The snapshot contains explicit Alembic
    # operations and deliberately does not import the live SQLAlchemy models.
    create_baseline_schema()


def downgrade() -> None:
    drop_baseline_schema()
