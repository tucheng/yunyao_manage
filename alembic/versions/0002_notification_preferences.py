"""Add notification targets and per-user reminder preferences.

Revision ID: 0002_notification_preferences
Revises: 0001_initial_schema
Create Date: 2026-07-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_notification_preferences"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user_settings", sa.Column("notification_preferences", sa.Text(), nullable=True))
    op.add_column("notifications", sa.Column("recipe_id", sa.Integer(), nullable=True))
    op.add_column("notifications", sa.Column("complaint_id", sa.Integer(), nullable=True))
    with op.batch_alter_table("notifications") as batch_op:
        batch_op.create_foreign_key(
            "fk_notifications_recipe_id_recipes",
            "recipes", ["recipe_id"], ["id"], ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_notifications_complaint_id_complaints",
            "complaints", ["complaint_id"], ["id"], ondelete="CASCADE",
        )


def downgrade() -> None:
    with op.batch_alter_table("notifications") as batch_op:
        batch_op.drop_constraint("fk_notifications_complaint_id_complaints", type_="foreignkey")
        batch_op.drop_constraint("fk_notifications_recipe_id_recipes", type_="foreignkey")
    op.drop_column("notifications", "complaint_id")
    op.drop_column("notifications", "recipe_id")
    op.drop_column("user_settings", "notification_preferences")
