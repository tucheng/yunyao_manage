from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from models import (
    Material,
    MaterialAlias,
    MaterialFamily,
    MaterialMergeLog,
    MaterialSubstitution,
    RecipeIngredient,
    SegerRecalculationJob,
)
from security import decrypt
from services.material_similarity import OXIDE_FIELDS


FINGERPRINT_FIELDS = OXIDE_FIELDS + ("thermal_expansion",)


def normalize_material_name(value: str | None) -> str:
    value = unicodedata.normalize("NFKD", str(value or "")).casefold()
    value = "".join(character for character in value if unicodedata.category(character) != "Mn")
    return re.sub(r"\s+", "", value)


def composition_fingerprint(material_or_data) -> str:
    def read(field):
        if isinstance(material_or_data, dict):
            return material_or_data.get(field)
        return getattr(material_or_data, field, None)

    values = [None if read(field) is None else round(float(read(field)), 6) for field in FINGERPRINT_FIELDS]
    return hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()


def ensure_material_family(db: Session, name: str) -> MaterialFamily:
    normalized = normalize_material_name(name)
    family = db.query(MaterialFamily).filter(MaterialFamily.normalized_name == normalized).first()
    if family:
        return family
    family = MaterialFamily(canonical_name=name.strip(), normalized_name=normalized)
    db.add(family)
    db.flush()
    return family


def register_material_aliases(db: Session, material: Material) -> None:
    if not material.family_id:
        return
    for alias, language in ((material.name, "zh"), (material.name_en, "en")):
        normalized = normalize_material_name(alias)
        if not normalized:
            continue
        existing = db.query(MaterialAlias.id).filter(
            MaterialAlias.normalized_alias == normalized,
            MaterialAlias.material_id == material.id,
        ).first()
        if not existing:
            db.add(MaterialAlias(
                family_id=material.family_id,
                material_id=material.id,
                alias=alias,
                normalized_alias=normalized,
                language=language,
                source=material.created_from or material.source or "",
            ))


def prepare_material(db: Session, material: Material) -> Material:
    material.normalized_name = normalize_material_name(material.name)
    material.composition_fingerprint = composition_fingerprint(material)
    if not material.family_id:
        family = ensure_material_family(db, material.name)
        material.family_id = family.id
        db.flush()
        if family.default_material_id is None and material.status == "recalculated":
            family.default_material_id = material.id
    register_material_aliases(db, material)
    return material


def _active_variant(db: Session, material_id: int | None) -> Material | None:
    if not material_id:
        return None
    return db.query(Material).filter(Material.id == material_id, Material.is_active.is_(True)).first()


def resolve_material(
    db: Session,
    *,
    name: str,
    name_en: str = "",
    owner_user_id: int | None = None,
    created_from: str = "frontend",
    create_missing: bool = True,
) -> tuple[Material | None, bool]:
    """Resolve a concrete variant, conservatively creating only truly missing names."""
    normalized_candidates = [normalize_material_name(name), normalize_material_name(name_en)]
    normalized_candidates = [value for value in dict.fromkeys(normalized_candidates) if value]

    for normalized in normalized_candidates:
        aliases = db.query(MaterialAlias).filter(MaterialAlias.normalized_alias == normalized).all()
        active_ids = {alias.material_id for alias in aliases if alias.material_id and _active_variant(db, alias.material_id)}
        if len(active_ids) == 1:
            return _active_variant(db, next(iter(active_ids))), False

    family = None
    for normalized in normalized_candidates:
        family = db.query(MaterialFamily).filter(MaterialFamily.normalized_name == normalized).first()
        if family:
            break
    if family:
        default = _active_variant(db, family.default_material_id)
        if default:
            return default, False
        variants = db.query(Material).filter(Material.family_id == family.id, Material.is_active.is_(True)).all()
        if len(variants) == 1:
            return variants[0], False
        return None, False

    if not create_missing or not normalize_material_name(name):
        return None, False

    family = ensure_material_family(db, name)
    material = Material(
        family_id=family.id,
        user_id=owner_user_id,
        name=name.strip(),
        name_en=name_en.strip(),
        normalized_name=normalize_material_name(name),
        source="user",
        created_from=created_from,
        status="initial",
        is_analysis=1,
        is_primitive=0,
        is_active=True,
        data_quality_status="normal",
    )
    material.composition_fingerprint = composition_fingerprint(material)
    db.add(material)
    db.flush()
    family.default_material_id = material.id
    register_material_aliases(db, material)
    return material, True


def resolve_recipe_ingredients(
    db: Session,
    recipe_id: int,
    *,
    owner_user_id: int | None,
    created_from: str,
    create_missing: bool = True,
) -> dict:
    created = []
    unresolved = []
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
                created.append({"id": material.id, "name": material.name})
        else:
            unresolved.append(name)
    db.flush()
    return {"linked": linked, "created": created, "unresolved": unresolved}


def affected_recipe_ids(db: Session, material_id: int) -> list[int]:
    rows = db.query(RecipeIngredient.recipe_id).filter(
        RecipeIngredient.material_id == material_id,
    ).distinct().all()
    return [row[0] for row in rows]


def backfill_recipe_material_links(db: Session, family_id: int | None = None) -> dict:
    if family_id is None:
        query = db.query(RecipeIngredient).filter(RecipeIngredient.material_id.is_(None))
    else:
        family_material_ids = db.query(Material.id).filter(Material.family_id == family_id)
        query = db.query(RecipeIngredient).filter(or_(
            RecipeIngredient.material_id.is_(None),
            RecipeIngredient.material_id.in_(family_material_ids),
        ))
    linked = 0
    unresolved = 0
    recipe_ids = set()
    for ingredient in query.yield_per(500):
        name = decrypt(ingredient.name, allow_plaintext=True) if ingredient.name else ""
        material, _ = resolve_material(
            db, name=name, name_en=ingredient.name_en or "", create_missing=False,
        )
        if material and (family_id is None or material.family_id == family_id):
            ingredient.material_id = material.id
            linked += 1
            recipe_ids.add(ingredient.recipe_id)
        else:
            unresolved += 1
    db.commit()
    return {"linked": linked, "unresolved": unresolved, "recipe_ids": sorted(recipe_ids)}


def duplicate_groups(db: Session) -> list[dict]:
    groups = (
        db.query(MaterialFamily, func.count(Material.id).label("variant_count"))
        .join(Material, Material.family_id == MaterialFamily.id)
        .filter(Material.is_active.is_(True))
        .group_by(MaterialFamily.id)
        .having(func.count(Material.id) > 1)
        .all()
    )
    result = []
    for family, count in groups:
        variants = db.query(Material).filter(Material.family_id == family.id, Material.is_active.is_(True)).all()
        fingerprints = {item.composition_fingerprint or composition_fingerprint(item) for item in variants}
        exact_clusters: dict[str, list[int]] = {}
        for item in variants:
            fingerprint = item.composition_fingerprint or composition_fingerprint(item)
            exact_clusters.setdefault(fingerprint, []).append(item.id)
        result.append({
            "family_id": family.id,
            "name": family.canonical_name,
            "default_material_id": family.default_material_id,
            "variant_count": count,
            "duplicate_type": "exact" if len(fingerprints) == 1 else "conflict",
            "exact_clusters": [ids for ids in exact_clusters.values() if len(ids) > 1],
            "affected_recipe_count": db.query(func.count(func.distinct(RecipeIngredient.recipe_id))).join(
                Material, RecipeIngredient.material_id == Material.id,
            ).filter(Material.family_id == family.id).scalar() or 0,
        })
    return sorted(result, key=lambda item: (-item["variant_count"], item["name"]))


def material_snapshot(material: Material) -> dict:
    return {column.name: getattr(material, column.name) for column in material.__table__.columns}


def merge_materials(
    db: Session,
    *,
    source: Material,
    target: Material,
    admin_user_id: int | None,
    reason: str,
    require_exact: bool = False,
) -> MaterialMergeLog:
    if source.id == target.id:
        raise ValueError("不能将材料合并到自身")
    if source.family_id != target.family_id:
        raise ValueError("只能合并同一材料族中的变体")
    if not source.is_active or not target.is_active:
        raise ValueError("只能合并有效材料")
    source_fp = source.composition_fingerprint or composition_fingerprint(source)
    target_fp = target.composition_fingerprint or composition_fingerprint(target)
    if require_exact and source_fp != target_fp:
        raise ValueError("材料成分不完全一致，不能自动合并")

    snapshot = material_snapshot(source)
    snapshot["recipe_ids"] = affected_recipe_ids(db, source.id)
    snapshot["ingredient_ids"] = [row[0] for row in db.query(RecipeIngredient.id).filter(
        RecipeIngredient.material_id == source.id,
    ).all()]
    snapshot["substitutions"] = [{
        "source_material_id": row.source_material_id,
        "target_material_id": row.target_material_id,
        "similarity_score": row.similarity_score,
        "status": row.status,
        "note": row.note,
    } for row in db.query(MaterialSubstitution).filter(or_(
        MaterialSubstitution.source_material_id == source.id,
        MaterialSubstitution.target_material_id == source.id,
    )).all()]
    snapshot["target_substitution_pairs_before"] = [list(row) for row in db.query(
        MaterialSubstitution.source_material_id, MaterialSubstitution.target_material_id,
    ).filter(or_(
        MaterialSubstitution.source_material_id == target.id,
        MaterialSubstitution.target_material_id == target.id,
    )).all()]
    snapshot["aliases"] = [{
        "alias": row.alias, "normalized_alias": row.normalized_alias,
        "language": row.language, "source": row.source,
    } for row in db.query(MaterialAlias).filter(MaterialAlias.material_id == source.id).all()]
    source_family = db.query(MaterialFamily).filter(MaterialFamily.id == source.family_id).first()
    snapshot["family_default_material_id"] = source_family.default_material_id if source_family else None
    db.query(RecipeIngredient).filter(RecipeIngredient.material_id == source.id).update(
        {RecipeIngredient.material_id: target.id}, synchronize_session=False,
    )

    substitutions = db.query(MaterialSubstitution).filter(or_(
        MaterialSubstitution.source_material_id == source.id,
        MaterialSubstitution.target_material_id == source.id,
    )).all()
    for relation in substitutions:
        new_source = target.id if relation.source_material_id == source.id else relation.source_material_id
        new_target = target.id if relation.target_material_id == source.id else relation.target_material_id
        if new_source == new_target:
            db.delete(relation)
            continue
        duplicate = db.query(MaterialSubstitution).filter(
            MaterialSubstitution.source_material_id == new_source,
            MaterialSubstitution.target_material_id == new_target,
            MaterialSubstitution.id != relation.id,
        ).first()
        if duplicate:
            duplicate.similarity_score = max(duplicate.similarity_score or 0, relation.similarity_score or 0)
            db.delete(relation)
        else:
            relation.source_material_id = new_source
            relation.target_material_id = new_target

    for alias in db.query(MaterialAlias).filter(MaterialAlias.material_id == source.id).all():
        duplicate = db.query(MaterialAlias).filter(
            MaterialAlias.material_id == target.id,
            MaterialAlias.normalized_alias == alias.normalized_alias,
        ).first()
        if duplicate:
            db.delete(alias)
        else:
            alias.material_id = target.id
            alias.family_id = target.family_id

    family = db.query(MaterialFamily).filter(MaterialFamily.id == source.family_id).first()
    if family and family.default_material_id == source.id:
        family.default_material_id = target.id if target.family_id == family.id else None
    source.is_active = False
    source.merged_into_id = target.id
    source.data_quality_status = "merged"
    log = MaterialMergeLog(
        source_material_id=source.id,
        target_material_id=target.id,
        reason=reason,
        snapshot_json=json.dumps(snapshot, ensure_ascii=False, default=str),
        merged_by=admin_user_id,
    )
    db.add(log)
    db.flush()
    return log


def rollback_material_merge(db: Session, log: MaterialMergeLog) -> dict:
    if log.rolled_back_at:
        raise ValueError("该合并记录已经回滚")
    snapshot = json.loads(log.snapshot_json or "{}")
    source = db.query(Material).filter(Material.id == log.source_material_id).first()
    target = db.query(Material).filter(Material.id == log.target_material_id).first()
    if not source or not target:
        raise ValueError("源材料或目标材料已不存在，无法回滚")

    ingredient_ids = [int(value) for value in snapshot.get("ingredient_ids", [])]
    if ingredient_ids:
        db.query(RecipeIngredient).filter(
            RecipeIngredient.id.in_(ingredient_ids),
            RecipeIngredient.material_id == target.id,
        ).update({RecipeIngredient.material_id: source.id}, synchronize_session=False)

    before_pairs = {tuple(pair) for pair in snapshot.get("target_substitution_pairs_before", [])}
    transformed_pairs = set()
    for row in snapshot.get("substitutions", []):
        new_source = target.id if row["source_material_id"] == source.id else row["source_material_id"]
        new_target = target.id if row["target_material_id"] == source.id else row["target_material_id"]
        if new_source != new_target:
            transformed_pairs.add((new_source, new_target))
    for pair in transformed_pairs - before_pairs:
        db.query(MaterialSubstitution).filter(
            MaterialSubstitution.source_material_id == pair[0],
            MaterialSubstitution.target_material_id == pair[1],
        ).delete(synchronize_session=False)
    for row in snapshot.get("substitutions", []):
        if row["source_material_id"] == row["target_material_id"]:
            continue
        existing = db.query(MaterialSubstitution).filter(
            MaterialSubstitution.source_material_id == row["source_material_id"],
            MaterialSubstitution.target_material_id == row["target_material_id"],
        ).first()
        if not existing:
            db.add(MaterialSubstitution(**row))

    for alias in snapshot.get("aliases", []):
        existing = db.query(MaterialAlias).filter(
            MaterialAlias.material_id == source.id,
            MaterialAlias.normalized_alias == alias["normalized_alias"],
        ).first()
        if not existing:
            db.add(MaterialAlias(family_id=source.family_id, material_id=source.id, **alias))

    source.is_active = True
    source.merged_into_id = None
    source.data_quality_status = snapshot.get("data_quality_status") or "normal"
    family = db.query(MaterialFamily).filter(MaterialFamily.id == source.family_id).first()
    if family and snapshot.get("family_default_material_id") == source.id:
        family.default_material_id = source.id
    log.rolled_back_at = datetime.now(timezone.utc)
    db.commit()
    return {"source_material_id": source.id, "target_material_id": target.id, "restored_ingredients": len(ingredient_ids)}


def recalculate_material_recipes(db: Session, material: Material) -> dict:
    from seger_calculator import calculate_seger

    recipe_ids = affected_recipe_ids(db, material.id)
    succeeded = 0
    failures = []
    for recipe_id in recipe_ids:
        job = SegerRecalculationJob(material_id=material.id, recipe_id=recipe_id, status="running", attempts=1)
        db.add(job)
        db.commit()
        job_id = job.id
        try:
            calculate_seger(recipe_id, db)
            job = db.query(SegerRecalculationJob).filter(SegerRecalculationJob.id == job_id).first()
            job.status = "succeeded"
            job.finished_at = datetime.now(timezone.utc)
            succeeded += 1
        except Exception as exc:  # keep every failed recipe retryable
            db.rollback()
            job = db.query(SegerRecalculationJob).filter(SegerRecalculationJob.id == job_id).first()
            job.status = "failed"
            job.error_message = str(exc)[:4000]
            job.finished_at = datetime.now(timezone.utc)
            failures.append({"recipe_id": recipe_id, "error": str(exc)})
        db.commit()
    return {"total": len(recipe_ids), "succeeded": succeeded, "failed": len(failures), "failures": failures}
