"""Add optional firing curve to recipes.

Revision ID: 0009_add_recipe_firing_curve
Revises: 0008_token_revocation
"""

from alembic import op
import sqlalchemy as sa


revision = "0009_add_recipe_firing_curve"
down_revision = "0008_token_revocation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("recipes", sa.Column("curve_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_recipes_curve_id_firing_curves",
        "recipes",
        "firing_curves",
        ["curve_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_recipes_curve_id_firing_curves", "recipes", type_="foreignkey")
    op.drop_column("recipes", "curve_id")
