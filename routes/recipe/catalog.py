import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from models import IngredientName, Recipe, Review, User
from schemas import RecipeListItem
from services.recipe_queries import (
    _distinct_public_recipe_values,
    _get_color_ranges,
    _public_recipe_query,
    _recipe_has_color_range,
    _recipe_matches_search_filters,
    _recipe_rows_with_work_counts,
    _serialize_recipe_list_item,
)
from services.recipe_serializers import search_review_payload

logger = logging.getLogger('yunyao')

router = APIRouter()

@router.get("/search/config")
def recipe_search_config(db: Session = Depends(get_db)):
    # 原料 — 从 IngredientName 表取
    rows = db.query(IngredientName.name).order_by(IngredientName.name).all()
    material_names = [r[0] for r in rows]

    return {
        "materials": material_names,
        "categories": _distinct_public_recipe_values(db, Recipe.category),
        "kiln_types": _distinct_public_recipe_values(db, Recipe.kiln_type),
        "atmospheres": _distinct_public_recipe_values(db, Recipe.atmosphere),
        "temperatures": _distinct_public_recipe_values(db, Recipe.temperature),
        "body_materials": _distinct_public_recipe_values(db, Recipe.body_material),
        "surfaces": _distinct_public_recipe_values(db, Recipe.surface),
        "transparencies": _distinct_public_recipe_values(db, Recipe.transparency),
        "color_ranges": _get_color_ranges(db),
        "has_work_options": [
            {"value": "yes", "label": "有作品"},
            {"value": "no", "label": "无作品"},
        ],
    }


@router.get("/count")
def count_recipes(
    type: str = "",
    category: str = "",
    keyword: str = "",
    author_id: int = 0,
    material: str = "",
    materials: str = "",
    has_work: str = "",
    atmosphere: str = "",
    body_material: str = "",
    surface: str = "",
    transparency: str = "",
    color: str = "",
    color_range: str = "",
    temperature: str = "",
    kiln_type: str = "",
    has_images: str = "",
    db: Session = Depends(get_db),
):
    query = _public_recipe_query(db)
    if type:
        query = query.filter(Recipe.type == type)
    if category:
        query = query.filter(Recipe.category == category)
    if atmosphere:
        query = query.filter(Recipe.atmosphere == atmosphere)
    if body_material:
        query = query.filter(Recipe.body_material == body_material)
    if author_id > 0:
        query = query.filter(Recipe.user_id == author_id)
    if keyword:
        query = query.filter(
            Recipe.title.contains(keyword)
        )
    if surface:
        query = query.filter(Recipe.surface == surface)
    if transparency:
        query = query.filter(Recipe.transparency == transparency)
    if temperature:
        query = query.filter(Recipe.temperature == temperature)
    if kiln_type:
        query = query.filter(Recipe.kiln_type == kiln_type)
    if has_images == "1":
        query = query.filter(
            (Recipe.cover != "") | (Recipe.images.isnot(None)) | (Recipe.images != "[]")
        )
    elif has_images == "0":
        query = query.filter(
            (Recipe.cover == "") & ((Recipe.images.is_(None)) | (Recipe.images == "[]"))
        )
    selected_color_range = color_range or color
    rows_query = _recipe_rows_with_work_counts(query)
    if not material and not materials and not has_work and not selected_color_range:
        return {"count": query.count()}
    color_ranges = _get_color_ranges(db) if selected_color_range else []
    count = 0
    for recipe, _, _, work_count, *_ in rows_query.all():
        if _recipe_matches_search_filters(recipe, material, has_work, work_count or 0, materials, db, selected_color_range, color_ranges):
            count += 1
    return {"count": count}


@router.get("/", response_model=list[RecipeListItem])
@router.get("", response_model=list[RecipeListItem], include_in_schema=False)
def list_recipes(
    type: str = "",
    category: str = "",
    keyword: str = "",
    author_id: int = 0,
    material: str = "",
    materials: str = "",
    has_work: str = "",
    atmosphere: str = "",
    body_material: str = "",
    surface: str = "",
    transparency: str = "",
    color: str = "",
    color_range: str = "",
    temperature: str = "",
    kiln_type: str = "",
    has_images: str = "",  # "1"=有图 "0"=无图
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    """列出公开服务（配方/烧制/找配方）"""
    query = _public_recipe_query(db)

    if type:
        query = query.filter(Recipe.type == type)
    if category:
        query = query.filter(Recipe.category == category)
    if atmosphere:
        query = query.filter(Recipe.atmosphere == atmosphere)
    if body_material:
        query = query.filter(Recipe.body_material == body_material)
    if author_id > 0:
        query = query.filter(Recipe.user_id == author_id)
    if keyword:
        query = query.filter(
            Recipe.title.contains(keyword)
            | Recipe.recipe_no.contains(keyword)
        )
    if surface:
        query = query.filter(Recipe.surface == surface)
    if transparency:
        query = query.filter(Recipe.transparency == transparency)
    if temperature:
        query = query.filter(Recipe.temperature == temperature)
    if kiln_type:
        query = query.filter(Recipe.kiln_type == kiln_type)
    if has_images == "1":
        query = query.filter(
            (Recipe.cover != "") | (Recipe.images.isnot(None)) | (Recipe.images != "[]")
        )
    elif has_images == "0":
        query = query.filter(
            (Recipe.cover == "") & ((Recipe.images.is_(None)) | (Recipe.images == "[]"))
        )

    selected_color_range = color_range or color
    color_ranges = _get_color_ranges(db) if selected_color_range else []
    rows_query = _recipe_rows_with_work_counts(query).order_by(Recipe.created_at.desc())
    if material or materials or has_work or selected_color_range:
        filtered_rows = []
        for recipe, nickname, avatar, work_count, work_image, work_images, fav_count in rows_query.all():
            if _recipe_matches_search_filters(recipe, material, has_work, work_count or 0, materials, db, selected_color_range, color_ranges):
                filtered_rows.append((recipe, nickname, avatar, work_count, work_image, work_images, fav_count))
        start = (page - 1) * page_size
        rows = filtered_rows[start:start + page_size]
    else:
        rows = (
            rows_query
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

    result = []
    for r, nickname, avatar, work_count, work_image, work_images, fav_count in rows:
        result.append(_serialize_recipe_list_item(r, nickname, avatar, work_count, work_image, work_images, fav_count))
    return result



@router.get("/search")
def search(
    keyword: str = "",
    q: str = "",
    body_material: str = "",
    category: str = "",
    atmosphere: str = "",
    kiln_type: str = "",
    surface: str = "",
    transparency: str = "",
    color: str = "",
    color_range: str = "",
    temperature: str = "",
    has_images: str = "",  # "1"=有图 "0"=无图
    author_id: int = 0,
    user_id: int = 0,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    """搜索配方 + 带图的评价作品"""
    keyword = keyword or q
    import logging
    logger = logging.getLogger('yunyao')
    logger.info(f"SEARCH: keyword={repr(keyword)}, page={page}, page_size={page_size}")
    # 1. 搜索配方
    recipe_query = db.query(Recipe).filter(
        Recipe.visibility.in_(["public", "showoff"])
    )
    if keyword:
        recipe_query = recipe_query.filter(
            (Recipe.recipe_no == keyword) | (Recipe.title.contains(keyword))
        )
    if body_material:
        recipe_query = recipe_query.filter(Recipe.body_material == body_material)
    if category:
        recipe_query = recipe_query.filter(Recipe.category == category)
    if atmosphere:
        recipe_query = recipe_query.filter(Recipe.atmosphere == atmosphere)
    if kiln_type:
        recipe_query = recipe_query.filter(Recipe.kiln_type == kiln_type)
    if surface:
        recipe_query = recipe_query.filter(Recipe.surface == surface)
    if transparency:
        recipe_query = recipe_query.filter(Recipe.transparency == transparency)
    if temperature:
        recipe_query = recipe_query.filter(Recipe.temperature == temperature)
    if has_images == "1":
        recipe_query = recipe_query.filter(
            (Recipe.cover != "") | (Recipe.images.isnot(None)) | (Recipe.images != "[]")
        )
    elif has_images == "0":
        recipe_query = recipe_query.filter(
            (Recipe.cover == "") & ((Recipe.images.is_(None)) | (Recipe.images == "[]"))
        )
    if author_id:
        recipe_query = recipe_query.filter(Recipe.user_id == author_id)

    selected_color_range = color_range or color
    ordered_recipe_query = recipe_query.order_by(Recipe.created_at.desc())
    if selected_color_range:
        color_ranges = _get_color_ranges(db)
        matched_recipes = [
            recipe for recipe in ordered_recipe_query.all()
            if _recipe_has_color_range(recipe, selected_color_range, color_ranges)
        ]
        start = (page - 1) * page_size
        recipes = matched_recipes[start:start + page_size]
    else:
        recipes = ordered_recipe_query.offset((page - 1) * page_size).limit(page_size).all()
    recipe_list = []
    for r in recipes:
        user = db.query(User).filter(User.id == r.user_id).first()
        setattr(r, "author_name", user.nickname if user else f"用户{r.user_id}")
        setattr(r, "avatar", user.avatar if user else "")
        recipe_list.append(r)

    # 2. 搜索带图的评价（作品图）
    review_query = db.query(Review).filter(
        Review.image != "",
        Review.image.isnot(None),
        Review.parent_id.is_(None),
    )
    if keyword:
        review_query = review_query.filter(
            Review.content.contains(keyword)
        )
    if body_material:
        review_query = review_query.filter(Review.body_material == body_material)
    if kiln_type:
        review_query = review_query.filter(Review.kiln_type == kiln_type)

    reviews = (
        review_query.order_by(Review.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    review_list = []
    for r in reviews:
        user = db.query(User).filter(User.id == r.user_id).first()
        recipe = db.query(Recipe).filter(Recipe.id == r.recipe_id).first()
        review_list.append(search_review_payload(r, user, recipe))

    return {
        "recipes": recipe_list,
        "works": review_list,
    }
