"""Add the owner of user-maintained material molecule data.

Revision ID: 0005_add_material_owner
Revises: 0004_align_attributes
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "0005_add_material_owner"
down_revision = "0004_align_attributes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = {column["name"] for column in inspector.get_columns("materials")}
    if "user_id" not in columns:
        op.add_column("materials", sa.Column("user_id", sa.Integer(), nullable=True))

    index_names = {index["name"] for index in inspect(conn).get_indexes("materials")}
    if "ix_materials_user_id" not in index_names:
        op.create_index("ix_materials_user_id", "materials", ["user_id"], unique=False)

    foreign_keys = inspect(conn).get_foreign_keys("materials")
    if not any(fk.get("constrained_columns") == ["user_id"] for fk in foreign_keys):
        op.create_foreign_key(
            "fk_materials_user_id_users",
            "materials",
            "users",
            ["user_id"],
            ["id"],
        )


def downgrade() -> None:
    conn = op.get_bind()
    columns = {column["name"] for column in inspect(conn).get_columns("materials")}
    if "user_id" not in columns:
        return

    foreign_keys = inspect(conn).get_foreign_keys("materials")
    for foreign_key in foreign_keys:
        if foreign_key.get("constrained_columns") == ["user_id"]:
            op.drop_constraint(foreign_key["name"], "materials", type_="foreignkey")
            break

    index_names = {index["name"] for index in inspect(conn).get_indexes("materials")}
    if "ix_materials_user_id" in index_names:
        op.drop_index("ix_materials_user_id", table_name="materials")
    op.drop_column("materials", "user_id")
