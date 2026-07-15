"""Production integrity constraints, FK policies, and secret cleanup.

Revision ID: 0007_production_hardening
Revises: 0006_complaint_workflow
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

from database import Base
import models  # noqa: F401

revision = "0007_production_hardening"
down_revision = "0006_complaint_workflow"
branch_labels = None
depends_on = None


UNIQUE_CONSTRAINTS = {
    "favorites": [("uq_favorite_user_recipe", ("user_id", "recipe_id")), ("uq_favorite_user_work", ("user_id", "work_id"))],
    "likes": [("uq_like_user_recipe", ("user_id", "recipe_id")), ("uq_like_user_work", ("user_id", "work_id"))],
    "follows": [("uq_follow_pair", ("follower_id", "followed_id"))],
    "redeem_logs": [("uq_redeem_log_code_user", ("code_id", "user_id"))],
    "recipe_versions": [("uq_recipe_version_no", ("recipe_id", "version_no"))],
    "material_substitutions": [("uq_material_substitution_pair", ("source_material_id", "target_material_id"))],
}

CHECK_CONSTRAINTS = {
    "favorites": [("ck_favorite_one_target", "(recipe_id IS NULL) <> (work_id IS NULL)")],
    "likes": [("ck_like_one_target", "(recipe_id IS NULL) <> (work_id IS NULL)")],
    "follows": [("ck_follow_not_self", "follower_id <> followed_id")],
    "redeem_codes": [
        ("ck_redeem_days_positive", "days > 0"),
        ("ck_redeem_max_uses_positive", "max_uses > 0"),
        ("ck_redeem_use_count", "current_uses >= 0 AND current_uses <= max_uses"),
    ],
    "redeem_logs": [("ck_redeem_log_days_positive", "days_added > 0")],
    "recipe_versions": [("ck_recipe_version_positive", "version_no > 0")],
    "material_substitutions": [
        ("ck_material_substitution_not_self", "source_material_id <> target_material_id"),
        ("ck_material_similarity_range", "similarity_score >= 0 AND similarity_score <= 100"),
    ],
}


def _dedupe(conn, table: str, columns: tuple[str, ...]) -> None:
    selected = ", ".join(["id", *columns])
    rows = conn.execute(sa.text(f"SELECT {selected} FROM {table} ORDER BY id")).mappings()
    seen = set()
    delete_ids = []
    for row in rows:
        key = tuple(row[column] for column in columns)
        if key in seen:
            delete_ids.append(row["id"])
        else:
            seen.add(key)
    if delete_ids:
        conn.execute(sa.text(f"DELETE FROM {table} WHERE id IN :ids").bindparams(sa.bindparam("ids", expanding=True)), {"ids": delete_ids})


def _clean_existing_data(conn) -> None:
    for table in ("favorites", "likes"):
        conn.execute(sa.text(f"DELETE FROM {table} WHERE recipe_id IS NULL AND work_id IS NULL"))
        conn.execute(sa.text(f"UPDATE {table} SET work_id = NULL WHERE recipe_id IS NOT NULL AND work_id IS NOT NULL"))
        _dedupe(conn, table, ("user_id", "recipe_id", "work_id"))
    conn.execute(sa.text("DELETE FROM follows WHERE follower_id = followed_id"))
    _dedupe(conn, "follows", ("follower_id", "followed_id"))
    _dedupe(conn, "redeem_logs", ("code_id", "user_id"))
    conn.execute(sa.text("UPDATE redeem_codes SET days = 1 WHERE days <= 0"))
    conn.execute(sa.text("UPDATE redeem_codes SET max_uses = 1 WHERE max_uses <= 0"))
    conn.execute(sa.text("UPDATE redeem_codes SET current_uses = 0 WHERE current_uses < 0"))
    conn.execute(sa.text("UPDATE redeem_codes SET current_uses = max_uses WHERE current_uses > max_uses"))
    conn.execute(sa.text("UPDATE redeem_logs SET days_added = 1 WHERE days_added <= 0"))
    conn.execute(sa.text("DELETE FROM material_substitutions WHERE source_material_id = target_material_id"))
    conn.execute(sa.text("UPDATE material_substitutions SET similarity_score = 0 WHERE similarity_score < 0 OR similarity_score IS NULL"))
    conn.execute(sa.text("UPDATE material_substitutions SET similarity_score = 100 WHERE similarity_score > 100"))
    _dedupe(conn, "material_substitutions", ("source_material_id", "target_material_id"))
    versions = conn.execute(sa.text("SELECT id, recipe_id FROM recipe_versions ORDER BY recipe_id, version_no, id")).mappings()
    counters: dict[int, int] = {}
    for row in versions:
        counters[row["recipe_id"]] = counters.get(row["recipe_id"], 0) + 1
        conn.execute(sa.text("UPDATE recipe_versions SET version_no=:version WHERE id=:id"), {"version": counters[row["recipe_id"]], "id": row["id"]})
    # A database row must never be treated as a secret store.
    conn.execute(sa.text("DELETE FROM app_settings WHERE `key` = 'smtp_password'"))


def _sync_foreign_keys(conn) -> None:
    if conn.dialect.name == "sqlite":
        return
    inspector = inspect(conn)
    for table_name, table in Base.metadata.tables.items():
        if table_name not in inspector.get_table_names():
            continue
        desired = {
            tuple(fk.parent.name for fk in constraint.elements): constraint
            for constraint in table.foreign_key_constraints
        }
        for existing in inspector.get_foreign_keys(table_name):
            columns = tuple(existing["constrained_columns"])
            target = desired.get(columns)
            if target is None or not existing.get("name"):
                continue
            wanted = (target.ondelete or "").upper()
            current = (existing.get("options", {}).get("ondelete") or "").upper()
            if current == wanted:
                continue
            op.drop_constraint(existing["name"], table_name, type_="foreignkey")
            element = next(iter(target.elements))
            op.create_foreign_key(
                f"fk_{table_name}_{'_'.join(columns)}",
                table_name,
                element.target_fullname.split(".")[0],
                list(columns),
                [item.target_fullname.split(".")[1] for item in target.elements],
                ondelete=target.ondelete,
            )


def upgrade() -> None:
    conn = op.get_bind()
    _clean_existing_data(conn)
    _sync_foreign_keys(conn)
    inspector = inspect(conn)
    for table, constraints in UNIQUE_CONSTRAINTS.items():
        existing = {item["name"] for item in inspector.get_unique_constraints(table)}
        existing.update(index["name"] for index in inspector.get_indexes(table) if index.get("unique"))
        for name, columns in constraints:
            if name not in existing:
                op.create_unique_constraint(name, table, list(columns))
    for table, constraints in CHECK_CONSTRAINTS.items():
        existing = {item["name"] for item in inspect(conn).get_check_constraints(table)}
        for name, condition in constraints:
            if name not in existing:
                op.create_check_constraint(name, table, condition)


def downgrade() -> None:
    conn = op.get_bind()
    for table, constraints in CHECK_CONSTRAINTS.items():
        existing = {item["name"] for item in inspect(conn).get_check_constraints(table)}
        for name, _condition in constraints:
            if name in existing:
                op.drop_constraint(name, table, type_="check")
    for table, constraints in UNIQUE_CONSTRAINTS.items():
        existing = {item["name"] for item in inspect(conn).get_unique_constraints(table)}
        for name, _columns in constraints:
            if name in existing:
                op.drop_constraint(name, table, type_="unique")
