"""Expand encrypted recipe ingredient amount storage.

Revision ID: 0010_expand_ingredient_amount
Revises: 0009_add_recipe_firing_curve
"""

from alembic import op
import sqlalchemy as sa


revision = "0010_expand_ingredient_amount"
down_revision = "0009_add_recipe_firing_curve"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "recipe_ingredients",
        "amount",
        existing_type=sa.String(length=100),
        type_=sa.String(length=500),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "recipe_ingredients",
        "amount",
        existing_type=sa.String(length=500),
        type_=sa.String(length=100),
        existing_nullable=True,
    )
