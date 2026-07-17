"""Add material families, review workflow and durable Seger recalculation jobs.

Revision ID: 0003_material_analysis_workflow
Revises: 0002_notification_preferences
Create Date: 2026-07-17
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_material_analysis_workflow"
down_revision: Union[str, None] = "0002_notification_preferences"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OXIDE_FIELDS = (
    "sio2", "al2o3", "fe2o3", "tio2", "cao", "mgo", "na2o", "k2o",
    "zno", "b2o3", "p2o5", "li2o", "mno2", "coo", "sno2", "cuo",
    "cr2o3", "pbo", "bao", "sro", "loi", "thermal_expansion",
)


def _normalize(value: str | None) -> str:
    value = unicodedata.normalize("NFKD", str(value or "")).casefold()
    value = "".join(character for character in value if unicodedata.category(character) != "Mn")
    return re.sub(r"\s+", "", value)


def _fingerprint(row: dict) -> str:
    values = [None if row.get(field) is None else round(float(row[field]), 6) for field in OXIDE_FIELDS]
    return hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()


def upgrade() -> None:
    op.create_table(
        "material_families",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("canonical_name", sa.String(200), nullable=False),
        sa.Column("normalized_name", sa.String(200), nullable=False),
        sa.Column("default_material_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("normalized_name", name="uq_material_families_normalized_name"),
        sa.ForeignKeyConstraint(["default_material_id"], ["materials.id"], ondelete="SET NULL"),
        mysql_collate="utf8mb4_bin",
    )
    op.create_index("ix_material_families_normalized_name", "material_families", ["normalized_name"])

    material_columns = (
        sa.Column("family_id", sa.Integer(), nullable=True),
        sa.Column("normalized_name", sa.String(200), nullable=True),
        sa.Column("variant_name", sa.String(200), nullable=True, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="recalculated"),
        sa.Column("created_from", sa.String(20), nullable=True, server_default="legacy"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("merged_into_id", sa.Integer(), nullable=True),
        sa.Column("composition_fingerprint", sa.String(64), nullable=True),
        sa.Column("data_quality_status", sa.String(20), nullable=False, server_default="normal"),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("recalculated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in material_columns:
        op.add_column("materials", column)
    with op.batch_alter_table("materials") as batch_op:
        batch_op.create_foreign_key("fk_materials_family", "material_families", ["family_id"], ["id"], ondelete="SET NULL")
        batch_op.create_foreign_key("fk_materials_merged_into", "materials", ["merged_into_id"], ["id"], ondelete="SET NULL")
        batch_op.create_foreign_key("fk_materials_reviewed_by", "users", ["reviewed_by"], ["id"], ondelete="SET NULL")
    op.create_index("ix_materials_family_id", "materials", ["family_id"])
    op.create_index("ix_materials_normalized_name", "materials", ["normalized_name"])
    op.create_index("ix_materials_merged_into_id", "materials", ["merged_into_id"])
    op.create_index("ix_materials_composition_fingerprint", "materials", ["composition_fingerprint"])

    op.add_column("recipe_ingredients", sa.Column("material_id", sa.Integer(), nullable=True))
    with op.batch_alter_table("recipe_ingredients") as batch_op:
        batch_op.create_foreign_key("fk_recipe_ingredients_material", "materials", ["material_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_recipe_ingredients_material_id", "recipe_ingredients", ["material_id"])
    op.create_index("ix_recipe_ingredients_material_recipe", "recipe_ingredients", ["material_id", "recipe_id"])

    op.add_column("recipe_seger", sa.Column("calculation_status", sa.String(20), nullable=False, server_default="complete"))
    op.add_column("recipe_seger", sa.Column("calculation_message", sa.Text(), nullable=True))

    op.create_table(
        "material_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("material_id", sa.Integer(), nullable=True),
        sa.Column("alias", sa.String(200), nullable=False),
        sa.Column("normalized_alias", sa.String(200), nullable=False),
        sa.Column("language", sa.String(20), server_default=""),
        sa.Column("source", sa.String(20), server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["family_id"], ["material_families.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["material_id"], ["materials.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("normalized_alias", "material_id", name="uq_material_alias_variant"),
        mysql_collate="utf8mb4_bin",
    )
    op.create_index("ix_material_aliases_family_id", "material_aliases", ["family_id"])
    op.create_index("ix_material_aliases_material_id", "material_aliases", ["material_id"])
    op.create_index("ix_material_aliases_normalized_alias", "material_aliases", ["normalized_alias"])

    op.create_table(
        "material_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("material_id", sa.Integer(), nullable=False),
        sa.Column("submitted_by", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="initial"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["material_id"], ["materials.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["submitted_by"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_material_revisions_material_id", "material_revisions", ["material_id"])
    op.create_index("ix_material_revisions_submitted_by", "material_revisions", ["submitted_by"])

    op.create_table(
        "material_merge_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_material_id", sa.Integer(), nullable=False),
        sa.Column("target_material_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(500), server_default=""),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("merged_by", sa.Integer(), nullable=True),
        sa.Column("merged_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["target_material_id"], ["materials.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["merged_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_material_merge_logs_source", "material_merge_logs", ["source_material_id"])
    op.create_index("ix_material_merge_logs_target", "material_merge_logs", ["target_material_id"])

    op.create_table(
        "seger_recalculation_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("material_id", sa.Integer(), nullable=False),
        sa.Column("recipe_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["material_id"], ["materials.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipes.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_seger_jobs_material_id", "seger_recalculation_jobs", ["material_id"])
    op.create_index("ix_seger_jobs_recipe_id", "seger_recalculation_jobs", ["recipe_id"])

    # Build one family per normalized generic name. Conflicting duplicate groups
    # intentionally get no default; an administrator must choose it explicitly.
    conn = op.get_bind()
    select_columns = [sa.column("id"), sa.column("name"), sa.column("name_en")] + [sa.column(field) for field in OXIDE_FIELDS]
    materials_table = sa.table("materials", *select_columns, sa.column("family_id"), sa.column("normalized_name"), sa.column("composition_fingerprint"))
    families_table = sa.table("material_families", sa.column("id"), sa.column("canonical_name"), sa.column("normalized_name"), sa.column("default_material_id"))
    aliases_table = sa.table("material_aliases", sa.column("family_id"), sa.column("material_id"), sa.column("alias"), sa.column("normalized_alias"), sa.column("language"), sa.column("source"))
    rows = [dict(row) for row in conn.execute(sa.select(*select_columns).select_from(materials_table)).mappings()]
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[_normalize(row["name"])].append(row)
    for normalized, group in grouped.items():
        if not normalized:
            continue
        fingerprints = {_fingerprint(row) for row in group}
        default_id = None
        if len(group) == 1 or len(fingerprints) == 1:
            default_id = max(group, key=lambda row: (sum(row.get(field) is not None for field in OXIDE_FIELDS), -row["id"]))["id"]
        conn.execute(sa.insert(families_table).values(
            canonical_name=group[0]["name"], normalized_name=normalized, default_material_id=default_id,
        ))
        family_id = conn.execute(
            sa.select(families_table.c.id).where(families_table.c.normalized_name == normalized)
        ).scalar_one()
        for row in group:
            fingerprint = _fingerprint(row)
            conn.execute(sa.update(materials_table).where(materials_table.c.id == row["id"]).values(
                family_id=family_id, normalized_name=normalized, composition_fingerprint=fingerprint,
            ))
            seen_aliases: set[str] = set()
            for alias, language in ((row["name"], "zh"), (row.get("name_en"), "en")):
                alias_normalized = _normalize(alias)
                if alias_normalized and alias_normalized not in seen_aliases:
                    seen_aliases.add(alias_normalized)
                    conn.execute(sa.insert(aliases_table).values(
                        family_id=family_id, material_id=row["id"], alias=alias,
                        normalized_alias=alias_normalized, language=language, source="migration",
                    ))


def downgrade() -> None:
    op.drop_table("seger_recalculation_jobs")
    op.drop_table("material_merge_logs")
    op.drop_table("material_revisions")
    op.drop_table("material_aliases")
    op.drop_column("recipe_seger", "calculation_message")
    op.drop_column("recipe_seger", "calculation_status")
    with op.batch_alter_table("recipe_ingredients") as batch_op:
        batch_op.drop_constraint("fk_recipe_ingredients_material", type_="foreignkey")
    op.drop_index("ix_recipe_ingredients_material_recipe", table_name="recipe_ingredients")
    op.drop_index("ix_recipe_ingredients_material_id", table_name="recipe_ingredients")
    op.drop_column("recipe_ingredients", "material_id")
    with op.batch_alter_table("materials") as batch_op:
        batch_op.drop_constraint("fk_materials_reviewed_by", type_="foreignkey")
        batch_op.drop_constraint("fk_materials_merged_into", type_="foreignkey")
        batch_op.drop_constraint("fk_materials_family", type_="foreignkey")
    for index in ("ix_materials_composition_fingerprint", "ix_materials_merged_into_id", "ix_materials_normalized_name", "ix_materials_family_id"):
        op.drop_index(index, table_name="materials")
    for column in (
        "updated_at", "recalculated_at", "review_note", "reviewed_by", "reviewed_at",
        "submitted_at", "data_quality_status", "composition_fingerprint", "merged_into_id",
        "is_active", "created_from", "status", "variant_name", "normalized_name", "family_id",
    ):
        op.drop_column("materials", column)
    op.drop_table("material_families")
