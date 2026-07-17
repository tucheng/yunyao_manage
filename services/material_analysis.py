from __future__ import annotations

import json
import re

from sqlalchemy.orm import Session

from models import Material, MaterialRecalculationLog, RecipeIngredient
from security import decrypt


def normalize_material_name(value: str | None) -> str:
    """材料身份仅忽略空白，保留大小写和重音符号。"""
    return re.sub(r"\s+", "", str(value or ""))


def prepare_material(db: Session, material: Material) -> Material:
    material.name = str(material.name or "").strip()
    material.name_en = str(material.name_en or "").strip()
    material.normalized_name = normalize_material_name(material.name)
    material.normalized_name_en = normalize_material_name(material.name_en)
    db.add(material)
    return material


def _matching_materials(db: Session, *, name: str = "", name_en: str = "") -> list[Material]:
    name_key = normalize_material_name(name)
    name_en_key = normalize_material_name(name_en)
    query = db.query(Material).filter(Material.is_active.is_(True))
    if name_key and name_en_key:
        query = query.filter(Material.normalized_name == name_key, Material.normalized_name_en == name_en_key)
    elif name_key:
        query = query.filter(Material.normalized_name == name_key)
    elif name_en_key:
        query = query.filter(Material.normalized_name_en == name_en_key)
    else:
        return []
    return query.order_by(
        (Material.status == "recalculated").desc(), Material.updated_at.desc(), Material.id.desc(),
    ).all()


def find_material_name_conflict(
    db: Session, *, name: str, name_en: str = "", exclude_id: int | None = None,
) -> Material | None:
    """只有中英文规范名同时相同才视为重名。"""
    name_key = normalize_material_name(name)
    name_en_key = normalize_material_name(name_en)
    if not name_key:
        return None
    query = db.query(Material).filter(
        Material.is_active.is_(True),
        Material.normalized_name == name_key,
        Material.normalized_name_en == name_en_key,
    )
    if exclude_id is not None:
        query = query.filter(Material.id != exclude_id)
    return query.order_by(Material.id).first()


def resolve_material(
    db: Session,
    *,
    name: str,
    name_en: str = "",
    owner_user_id: int | None = None,
    created_from: str = "frontend",
    create_missing: bool = True,
) -> tuple[Material | None, bool]:
    """中英文都有时联合匹配，只有一个名称时使用该名称匹配。"""
    matches = _matching_materials(db, name=name, name_en=name_en)
    if matches:
        return matches[0], False
    if not create_missing or not normalize_material_name(name):
        return None, False
    material = Material(
        user_id=owner_user_id,
        name=str(name or "").strip(),
        name_en=str(name_en or "").strip(),
        source="user",
        created_from=created_from,
        status="initial",
        is_analysis=1,
        is_primitive=0,
    )
    prepare_material(db, material)
    db.flush()
    return material, True


def resolve_recipe_ingredients(
    db: Session,
    recipe_id: int,
    *,
    owner_user_id: int | None,
    created_from: str,
    create_missing: bool = True,
) -> dict:
    created, unresolved = [], []
    linked = 0
    ingredients = db.query(RecipeIngredient).filter(RecipeIngredient.recipe_id == recipe_id).all()
    for ingredient in ingredients:
        name = decrypt(ingredient.name, allow_plaintext=True) if ingredient.name else ""
        material, was_created = resolve_material(
            db,
            name=name,
            name_en=ingredient.name_en or "",
            owner_user_id=owner_user_id,
            created_from=created_from,
            create_missing=create_missing,
        )
        ingredient.material_id = material.id if material else None
        if material:
            linked += 1
            if was_created:
                created.append({"id": material.id, "name": material.name, "name_en": material.name_en})
        else:
            unresolved.append(name)
    db.flush()
    return {"linked": linked, "created": created, "unresolved": unresolved}


def affected_recipe_ids(db: Session, material_id: int) -> list[int]:
    rows = db.query(RecipeIngredient.recipe_id).filter(
        RecipeIngredient.material_id == material_id,
    ).distinct().order_by(RecipeIngredient.recipe_id).all()
    return [row[0] for row in rows]


def backfill_recipe_material_links(db: Session) -> dict:
    ingredients = db.query(RecipeIngredient).filter(RecipeIngredient.material_id.is_(None)).all()
    linked, unresolved = 0, 0
    recipe_ids = set()
    for ingredient in ingredients:
        name = decrypt(ingredient.name, allow_plaintext=True) if ingredient.name else ""
        material, _ = resolve_material(db, name=name, name_en=ingredient.name_en or "", create_missing=False)
        if material:
            ingredient.material_id = material.id
            linked += 1
            recipe_ids.add(ingredient.recipe_id)
        else:
            unresolved += 1
    db.commit()
    return {"linked": linked, "unresolved": unresolved, "recipe_ids": sorted(recipe_ids)}


def recalculate_material_recipes(
    db: Session, material: Material, *, admin_user_id: int | None = None,
) -> dict:
    from seger_calculator import calculate_seger

    recipe_ids = affected_recipe_ids(db, material.id)
    succeeded, failures = 0, []
    for recipe_id in recipe_ids:
        try:
            calculate_seger(recipe_id, db)
            succeeded += 1
        except Exception as exc:
            db.rollback()
            failures.append({"recipe_id": recipe_id, "error": str(exc)[:2000]})
    log = MaterialRecalculationLog(
        material_id=material.id,
        admin_id=admin_user_id,
        affected_recipe_count=len(recipe_ids),
        success_count=succeeded,
        failed_count=len(failures),
        recipe_ids_json=json.dumps(recipe_ids, ensure_ascii=False),
        failures_json=json.dumps(failures, ensure_ascii=False),
    )
    db.add(log)
    db.commit()
    return {
        "total": len(recipe_ids), "succeeded": succeeded, "failed": len(failures),
        "failures": failures, "recipe_ids": recipe_ids, "log_id": log.id,
    }
