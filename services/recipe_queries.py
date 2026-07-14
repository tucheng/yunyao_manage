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
from auth_utils import user_id_from_request
from sqlalchemy import func
from seger_calculator import calculate_seger
from services.recipe_version import snapshot_recipe
from color_names import color_name_in_range, get_color_range_config
import json
import logging
from datetime import datetime

logger = logging.getLogger('yunyao')

__all__ = [
    "_public_recipe_query",
    "_get_color_ranges",
    "_color_name_in_ranges",
    "_recipe_has_color_range",
    "_distinct_public_recipe_values",
    "_recipe_ingredient_names",
    "_recipe_has_material",
    "_recipe_has_all_materials",
    "_recipe_has_work",
    "_recipe_matches_search_filters",
    "_recipe_rows_with_work_counts",
    "_first_work_image",
    "_serialize_recipe_list_item",
]

def _public_recipe_query(db: Session):
    return db.query(Recipe).filter(
        Recipe.visibility.in_(["public", "showoff"])
    )


def _get_color_ranges(db: Session) -> list:
    row = db.query(AppSetting).filter(AppSetting.key == "work_search_color_ranges").first()
    if row and row.value:
        try:
            value = json.loads(row.value)
            if isinstance(value, list):
                return value
        except Exception:
            pass
    return get_color_range_config()


def _color_name_in_ranges(name: str, range_value: str, color_ranges: list) -> bool:
    if not name or not range_value:
        return False
    for item in color_ranges:
        if item.get("value") == range_value:
            return name in (item.get("names") or [])
    return color_name_in_range(name, range_value)


def _recipe_has_color_range(recipe: Recipe, range_value: str, color_ranges: list) -> bool:
    if not range_value:
        return True
    try:
        colors = json.loads(recipe.glaze_colors) if recipe.glaze_colors else []
    except Exception:
        colors = []
    if not isinstance(colors, list):
        return False
    return any(
        _color_name_in_ranges((item or {}).get("name", ""), range_value, color_ranges)
        for item in colors
        if isinstance(item, dict)
    )


def _distinct_public_recipe_values(db: Session, column) -> list[str]:
    return [row[0] for row in db.query(column).filter(
        column != "",
        column.isnot(None),
        Recipe.visibility.in_(["public", "showoff"]),
    ).distinct().order_by(column).all()]


def _recipe_ingredient_names(recipe_id: int, db: Session) -> list[str]:
    """从 recipe_ingredients 表查原料名称（解密后返回）"""
    rows = db.query(RecipeIngredient.name).filter(
        RecipeIngredient.recipe_id == recipe_id
    ).all()
    return [decrypt(r[0]) for r in rows if r[0]]


def _recipe_has_material(recipe: Recipe, material: str, db: Session) -> bool:
    material = (material or "").strip()
    if not material:
        return True
    h = hash_for_lookup(material)
    return db.query(RecipeIngredient.id).filter(
        RecipeIngredient.recipe_id == recipe.id,
        RecipeIngredient.name_hash == h,
    ).first() is not None


def _recipe_has_all_materials(recipe: Recipe, materials_str: str, db: Session) -> bool:
    """AND 逻辑：配方必须包含所有指定的原料（哈希匹配）"""
    if not materials_str:
        return True
    materials = [m.strip() for m in materials_str.split(",") if m.strip()]
    if not materials:
        return True
    hashes = [hash_for_lookup(m) for m in materials]
    count = db.query(RecipeIngredient.id).filter(
        RecipeIngredient.recipe_id == recipe.id,
        RecipeIngredient.name_hash.in_(hashes),
    ).count()
    return count == len(hashes)


def _recipe_has_work(recipe: Recipe, work_count: int) -> bool:
    return bool(work_count and work_count > 0)


def _recipe_matches_search_filters(
    recipe: Recipe,
    material: str,
    has_work: str,
    work_count: int,
    materials: str = "",
    db: Session = None,
    color_range: str = "",
    color_ranges: list | None = None,
) -> bool:
    if material and not _recipe_has_material(recipe, material, db):
        return False
    if materials and not _recipe_has_all_materials(recipe, materials, db):
        return False
    has_linked_work = _recipe_has_work(recipe, work_count)
    if has_work == "yes" and not has_linked_work:
        return False
    if has_work == "no" and has_linked_work:
        return False
    if color_range and not _recipe_has_color_range(recipe, color_range, color_ranges or []):
        return False
    return True


def _recipe_rows_with_work_counts(query):
    work_counts = (
        query.session.query(Work.recipe_id, func.count(Work.id).label("work_count"))
        .group_by(Work.recipe_id)
        .subquery()
    )
    # favorite count subquery
    fav_counts = (
        query.session.query(Favorite.recipe_id, func.count(Favorite.id).label("fav_count"))
        .filter(Favorite.recipe_id.isnot(None))
        .group_by(Favorite.recipe_id)
        .subquery()
    )
    # latest work per recipe via window function (works on MariaDB & MySQL)
    latest_work_subq = (
        query.session.query(
            Work.recipe_id,
            Work.image,
            Work.images,
            func.row_number().over(
                partition_by=Work.recipe_id,
                order_by=Work.created_at.desc()
            ).label("rn")
        )
        .subquery()
    )
    first_work = (
        query.session.query(
            latest_work_subq.c.recipe_id,
            latest_work_subq.c.image,
            latest_work_subq.c.images,
        )
        .filter(latest_work_subq.c.rn == 1)
        .subquery()
    )
    return (
        query.outerjoin(User, Recipe.user_id == User.id)
        .outerjoin(work_counts, Recipe.id == work_counts.c.recipe_id)
        .outerjoin(fav_counts, Recipe.id == fav_counts.c.recipe_id)
        .outerjoin(first_work, Recipe.id == first_work.c.recipe_id)
        .with_entities(Recipe, User.nickname, User.avatar, work_counts.c.work_count, first_work.c.image, first_work.c.images, fav_counts.c.fav_count)
    )


def _first_work_image(work_image: str, work_images_json: str) -> str:
    """从作品字段中提取第一张图片URL"""
    images = parse_image_list(work_images_json)
    return images[0] if images else normalize_image_url(work_image)


def _serialize_recipe_list_item(recipe, nickname, avatar, work_count=0, work_image="", work_images="", favorite_count=0):
    setattr(recipe, 'author_name', nickname if nickname else f'用户{recipe.user_id}')
    setattr(recipe, 'avatar', avatar or "")
    setattr(recipe, 'work_count', work_count or 0)
    setattr(recipe, 'work_image', _first_work_image(work_image, work_images))
    setattr(recipe, 'favorite_count', favorite_count or 0)
    return recipe

