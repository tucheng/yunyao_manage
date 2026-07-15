from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session, joinedload
from database import get_db
from models import AppSetting, Recipe, User, Review, Favorite, Work, RecipeSequence, Like, RecipeView, RecipeIngredient, IngredientName, RecipeSeger, RecipeVersion
from schemas import (
    RecipeCreate, RecipeUpdate, RecipeOut, RecipeListItem,
    ReviewCreate, ReviewOut,
)
from security import encrypt, decrypt, hash_for_lookup
from image_utils import normalize_image_url, parse_image_list, serialize_image_list
from auth_utils import current_user, user_id_from_request
from sqlalchemy import func
from seger_calculator import calculate_seger
from services.recipe_version import snapshot_recipe
from color_names import color_name_in_range, get_color_range_config
import json
import logging
from datetime import datetime

logger = logging.getLogger('yunyao')

router = APIRouter()

@router.get("/{recipe_id}/versions")
def list_recipe_versions(recipe_id: int, db: Session = Depends(get_db)):
    """获取配方历史版本列表"""
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="配方不存在")
    versions = db.query(RecipeVersion).filter(
        RecipeVersion.recipe_id == recipe_id
    ).order_by(RecipeVersion.version_no.desc()).all()
    return [{
        "id": v.id,
        "version_no": v.version_no,
        "note": v.note or "",
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "created_by": v.created_by,
    } for v in versions]


@router.get("/{recipe_id}/versions/{version_id}")
def get_recipe_version_detail(recipe_id: int, version_id: int, db: Session = Depends(get_db)):
    """获取某个版本的完整数据"""
    version = db.query(RecipeVersion).filter(
        RecipeVersion.id == version_id,
        RecipeVersion.recipe_id == recipe_id,
    ).first()
    if not version:
        raise HTTPException(status_code=404, detail="版本不存在")
    return {
        "id": version.id,
        "version_no": version.version_no,
        "note": version.note or "",
        "created_at": version.created_at.isoformat() if version.created_at else None,
        "recipe_data": json.loads(version.recipe_data),
        "ingredients_data": json.loads(version.ingredients_data),
        "seger_data": json.loads(version.seger_data) if version.seger_data else None,
    }


@router.post("/{recipe_id}/versions/{version_id}/restore", dependencies=[Depends(current_user)])
def restore_recipe_version(
    recipe_id: int, version_id: int,
    user_id: int = Query(...),
    db: Session = Depends(get_db),
):
    """恢复到指定历史版本"""
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="配方不存在")
    if recipe.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权操作")

    # 先快照当前状态（防止恢复错了想回退）
    prev_version_no = db.query(RecipeVersion.version_no).filter(
        RecipeVersion.id == version_id, RecipeVersion.recipe_id == recipe_id
    ).scalar()
    snapshot_recipe(recipe_id, db, note=f"还原到 v{prev_version_no or '?'}", user_id=user_id)

    version = db.query(RecipeVersion).filter(
        RecipeVersion.id == version_id,
        RecipeVersion.recipe_id == recipe_id,
    ).first()
    if not version:
        raise HTTPException(status_code=404, detail="版本不存在")

    # 恢复 recipe 字段
    recipe_data = json.loads(version.recipe_data)
    for key, value in recipe_data.items():
        if hasattr(recipe, key) and key not in ("id", "user_id", "created_at", "recipe_no"):
            setattr(recipe, key, value)
    recipe.updated_at = func.now()
    db.flush()

    # 恢复 ingredients
    db.query(RecipeIngredient).filter(RecipeIngredient.recipe_id == recipe_id).delete()
    ing_list = json.loads(version.ingredients_data)
    for i, item in enumerate(ing_list):
        raw_name = (item.get("name") or "").strip()
        ing = RecipeIngredient(
            recipe_id=recipe_id,
            recipe_no=recipe.recipe_no or "",
            name=encrypt(raw_name),
            name_en=(item.get("name_en") or "").strip(),
            name_hash=hash_for_lookup(raw_name),
            amount=encrypt(str(item.get("amount") or "").strip()),
            unit=str(item.get("unit") or "").strip()[:20],
            note=item.get("note") or "",
            is_additional=1 if item.get("is_additional") else 0,
            sort_order=item.get("sort_order", i),
        )
        db.add(ing)
    db.commit()

    # 重新计算 Seger
    try:
        calculate_seger(recipe_id, db)
    except Exception as e:
        logger.error("Seger recalculation failed after restore recipe %s: %s", recipe_id, e)

    db.refresh(recipe)
    return recipe
