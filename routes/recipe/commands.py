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

router = APIRouter(dependencies=[Depends(current_user)])

from services.recipe_number import generate_recipe_no

@router.post("/", response_model=RecipeOut)
def create_recipe(recipe: RecipeCreate, user_id: int = Query(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    from services.user_quota import consume_quota
    consume_quota(db, user, "recipe")

    # 处理釉色数据
    glaze_colors_json = "[]"
    if recipe.glaze_colors:
        # 支持 JSON 字符串或数组
        try:
            raw = json.loads(recipe.glaze_colors) if isinstance(recipe.glaze_colors, str) else recipe.glaze_colors
            if isinstance(raw, list):
                from color_names import get_glaze_colors_data
                hex_list = []
                for c in raw:
                    if isinstance(c, dict):
                        hex_list.append(c.get("hex", ""))
                    elif isinstance(c, str):
                        hex_list.append(c)
                    else:
                        hex_list.append(str(c))
                hex_list = [h for h in hex_list if h]
                colors_data = get_glaze_colors_data(hex_list) if hex_list else []
                glaze_colors_json = json.dumps(colors_data, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            glaze_colors_json = recipe.glaze_colors

    cover = normalize_image_url(recipe.cover)
    images = parse_image_list(recipe.images)
    if cover and cover not in images:
        images.insert(0, cover)
    if not cover and images:
        cover = images[0]

    db_recipe = Recipe(
        user_id=user_id,
        title=recipe.title,
        recipe_no=generate_recipe_no(db),
        type=recipe.type,
        cover=cover,
        images=serialize_image_list(images),
        describe=recipe.describe,
        category=recipe.category,
        temperature=recipe.temperature,
        atmosphere=recipe.atmosphere,
        kiln_type=recipe.kiln_type,
        body_material=recipe.body_material,
        surface=recipe.surface,
        transparency=recipe.transparency,
        visibility=recipe.visibility if recipe.visibility in ("public", "private", "showoff") else "private",
        forked_from=recipe.forked_from,
        glaze_colors=glaze_colors_json,
    )
    db.add(db_recipe)
    db.commit()
    db.refresh(db_recipe)
    if recipe.work_id:
        work = db.query(Work).filter(Work.id == recipe.work_id).first()
        if work and work.user_id == user_id:
            work.recipe_id = db_recipe.id
            db.commit()
    # Trigger Seger formula calculation
    try:
        calculate_seger(db_recipe.id, db)
        logger.info("Seger calculation completed for recipe %s", db_recipe.id)
    except Exception as e:
        logger.error("Seger calculation failed for recipe %s: %s", db_recipe.id, e)
    return db_recipe


@router.put("/{recipe_id}", response_model=RecipeOut)
def update_recipe(
    recipe_id: int,
    recipe: RecipeUpdate,
    user_id: int = Query(...),
    db: Session = Depends(get_db),
):
    db_recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not db_recipe:
        raise HTTPException(status_code=404, detail="不存在")
    if db_recipe.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权修改")

    # 快照当前状态
    snapshot_recipe(recipe_id, db, note="编辑配方信息", user_id=user_id)

    update_data = recipe.model_dump(exclude_unset=True)
    if "cover" in update_data or "images" in update_data:
        cover = normalize_image_url(update_data.get("cover", db_recipe.cover))
        images = parse_image_list(update_data.get("images", db_recipe.images))
        if cover and cover not in images:
            images.insert(0, cover)
        if not cover and images:
            cover = images[0]
        update_data["cover"] = cover
        update_data["images"] = serialize_image_list(images)
    if update_data.get("visibility") not in (None, "public", "private", "showoff"):
        raise HTTPException(status_code=400, detail="不支持的可见范围")

    # 处理釉色数据
    if "glaze_colors" in update_data and update_data["glaze_colors"]:
        gc = update_data["glaze_colors"]
        try:
            raw = json.loads(gc) if isinstance(gc, str) else gc
            if isinstance(raw, list):
                from color_names import get_glaze_colors_data
                hex_list = []
                for c in raw:
                    if isinstance(c, dict):
                        hex_list.append(c.get("hex", ""))
                    elif isinstance(c, str):
                        hex_list.append(c)
                    else:
                        hex_list.append(str(c))
                hex_list = [h for h in hex_list if h]
                colors_data = get_glaze_colors_data(hex_list) if hex_list else []
                update_data["glaze_colors"] = json.dumps(colors_data, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            pass  # keep original value
    for key, value in update_data.items():
        setattr(db_recipe, key, value)
    db_recipe.updated_at = func.now()
    db.commit()
    db.refresh(db_recipe)
    # Trigger Seger formula calculation
    try:
        calculate_seger(db_recipe.id, db)
        logger.info("Seger calculation completed for recipe %s", db_recipe.id)
    except Exception as e:
        logger.error("Seger calculation failed for recipe %s: %s", db_recipe.id, e)
    return db_recipe


@router.delete("/{recipe_id}")
def delete_recipe(recipe_id: int, user_id: int = Query(...), db: Session = Depends(get_db)):
    db_recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not db_recipe:
        raise HTTPException(status_code=404, detail="不存在")
    if db_recipe.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权删除")
    db.delete(db_recipe)
    db.commit()
    return {"message": "已删除"}
