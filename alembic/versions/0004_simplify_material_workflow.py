"""Simplify material matching, review and recalculation logging.

Revision ID: 0004_simplify_material_workflow
Revises: 0003_material_analysis_workflow
Create Date: 2026-07-17
"""
from __future__ import annotations

import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004_simplify_material_workflow"
down_revision: Union[str, None] = "0003_material_analysis_workflow"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _normalize(value: str | None) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def upgrade() -> None:
    op.add_column("materials", sa.Column("normalized_name_en", sa.String(200), nullable=True, server_default=""))
    op.create_index("ix_materials_normalized_name_en", "materials", ["normalized_name_en"])

    conn = op.get_bind()
    materials = sa.table(
        "materials",
        sa.column("id", sa.Integer()),
        sa.column("name", sa.String()),
        sa.column("name_en", sa.String()),
        sa.column("normalized_name", sa.String()),
        sa.column("normalized_name_en", sa.String()),
    )
    rows = conn.execute(sa.select(materials.c.id, materials.c.name, materials.c.name_en)).mappings()
    for row in rows:
        conn.execute(
            sa.update(materials).where(materials.c.id == row["id"]).values(
                normalized_name=_normalize(row["name"]),
                normalized_name_en=_normalize(row["name_en"]),
            )
        )

    op.create_table(
        "material_recalculation_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("material_id", sa.Integer(), nullable=False),
        sa.Column("admin_id", sa.Integer(), nullable=True),
        sa.Column("affected_recipe_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recipe_ids_json", sa.Text(), nullable=False),
        sa.Column("failures_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["material_id"], ["materials.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["admin_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_material_recalculation_logs_material_id", "material_recalculation_logs", ["material_id"])
    op.create_index("ix_material_recalculation_logs_admin_id", "material_recalculation_logs", ["admin_id"])

    # Remove the family/alias/merge/revision/job structures. Historical inactive
    # material rows remain hidden through materials.is_active so no data is deleted.
    op.drop_table("seger_recalculation_jobs")
    op.drop_table("material_merge_logs")
    op.drop_table("material_revisions")
    op.drop_table("material_aliases")

    with op.batch_alter_table("materials") as batch_op:
        batch_op.drop_constraint("fk_materials_merged_into", type_="foreignkey")
        batch_op.drop_constraint("fk_materials_family", type_="foreignkey")
    for index in (
        "ix_materials_composition_fingerprint",
        "ix_materials_merged_into_id",
        "ix_materials_family_id",
    ):
        op.drop_index(index, table_name="materials")
    for column in (
        "data_quality_status",
        "composition_fingerprint",
        "merged_into_id",
        "variant_name",
        "family_id",
    ):
        op.drop_column("materials", column)
    op.drop_table("material_families")


def downgrade() -> None:
    raise RuntimeError(
        "0004 removes obsolete material family and merge structures; restore the pre-migration backup to downgrade."
    )
