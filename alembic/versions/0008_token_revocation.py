"""Add token revocation and repair recipe work counters.

Revision ID: 0008_token_revocation
Revises: 0007_production_hardening
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_token_revocation"
down_revision = "0007_production_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.execute(
        "UPDATE recipes SET work_count = "
        "(SELECT COUNT(*) FROM works WHERE works.recipe_id = recipes.id)"
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
