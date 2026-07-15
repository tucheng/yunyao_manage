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
from services.recipe_access import require_recipe_reader
from sqlalchemy import func
from seger_calculator import calculate_seger
from services.recipe_version import snapshot_recipe
from color_names import color_name_in_range, get_color_range_config
import json
import logging
from datetime import datetime

logger = logging.getLogger('yunyao')

router = APIRouter()

from services.recipe_queries import *

@router.get("/by-no/{recipe_no}")
def get_recipe_by_no(recipe_no: str, request: Request, db: Session = Depends(get_db)):
    recipe = db.query(Recipe).filter(Recipe.recipe_no == recipe_no).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="查不出此编号对应的配方")
    require_recipe_reader(db, recipe, user_id_from_request(request), consume_quota=True)
    db.commit()
    return recipe

# ========= 详情 =========

@router.get("/{recipe_id}", response_model=RecipeOut)
def get_recipe(
    recipe_id: int,
    request: Request,
    user_id: int = 0,
    db: Session = Depends(get_db),
):
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="不存在")
    current_user_id = user_id_from_request(request)
    require_recipe_reader(db, recipe, current_user_id, consume_quota=True)
    db.commit()

    # 收藏状态
    recipe.is_favorited = False
    if current_user_id > 0:
        fav = db.query(Favorite).filter(
            Favorite.recipe_id == recipe_id,
            Favorite.user_id == current_user_id,
        ).first()
        if fav:
            recipe.is_favorited = True

    # 点赞状态
    recipe.is_liked = False
    if current_user_id > 0:
        liked = db.query(Like).filter(
            Like.recipe_id == recipe_id,
            Like.user_id == current_user_id,
        ).first()
        if liked:
            recipe.is_liked = True


    # 带上作者名和头像
    user = db.query(User).filter(User.id == recipe.user_id).first()
    recipe.author_name = user.nickname if user else f'用户{recipe.user_id}'
    recipe.avatar = user.avatar if user else ''

    # 平均评分
    avg = db.query(func.avg(Review.rating)).filter(
        Review.recipe_id == recipe_id,
        Review.parent_id.is_(None),
    ).scalar()
    recipe.rating_avg = round(float(avg), 1) if avg else 0

    # 收藏数
    recipe.favorite_count = db.query(Favorite).filter(
        Favorite.recipe_id == recipe_id,
    ).count()

    # 关联作品数
    recipe.works_count = db.query(Work).filter(
        Work.recipe_id == recipe_id,
    ).count()

    # 原料状态表（减少前端的额外查询）
    recipe.ingredient_statuses = {}
    if current_user_id > 0:
        from models import UserMaterial
        materials = db.query(UserMaterial).filter(
            UserMaterial.user_id == current_user_id,
        ).all()
        for m in materials:
            recipe.ingredient_statuses[m.name.strip().lower()] = m.status

    return recipe


# ========= Seger 辅助函数 =========


def _parse_seger_detail(detail_json: str) -> dict:
    """Parse seger_detail JSON and extract summary fields."""
    if not detail_json or detail_json == "{}":
        return {"unmatched": [], "included_additional": [], "found_no_oxides": [],
                "surface_prediction": {"surface": "", "note": ""},
                "firing_temp": {"cone": "", "temp_range": "", "note": ""},
                "thermal_expansion": {"na_k_ratio": 0, "details": []},
                "color_analysis": {"hints": []},
                "oxide_contributions": {}}
    try:
        detail = json.loads(detail_json)
        return {
            "unmatched": detail.get("unmatched", []),
            # Older saved calculations used a misleading key name even though
            # additives were included in the oxide accumulation.
            "included_additional": detail.get(
                "included_additional", detail.get("skipped_additional", [])
            ),
            "found_no_oxides": detail.get("found_no_oxides", []),
            "surface_prediction": detail.get("surface_prediction", {"surface": "", "note": ""}),
            "firing_temp": detail.get("firing_temp", {"cone": "", "temp_range": "", "note": ""}),
            "thermal_expansion": detail.get("thermal_expansion", {"na_k_ratio": 0, "details": []}),
            "color_analysis": detail.get("color_analysis", {"hints": []}),
            "oxide_contributions": detail.get("oxide_contributions", {}),
        }
    except (json.JSONDecodeError, TypeError):
        return {"unmatched": [], "included_additional": [], "found_no_oxides": [],
                "surface_prediction": {"surface": "", "note": ""},
                "firing_temp": {"cone": "", "temp_range": "", "note": ""},
                "thermal_expansion": {"na_k_ratio": 0, "details": []},
                "color_analysis": {"hints": []},
                "oxide_contributions": {}}


@router.get("/{recipe_id}/seger")
def get_recipe_seger(recipe_id: int, request: Request, db: Session = Depends(get_db)):
    """获取配方的 Seger 公式计算结果"""
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="配方不存在")
    require_recipe_reader(db, recipe, user_id_from_request(request), consume_quota=True)
    db.commit()

    seger = db.query(RecipeSeger).filter(RecipeSeger.recipe_id == recipe_id).first()
    if not seger:
        detail_info = {"unmatched": [], "included_additional": [], "found_no_oxides": []}
        return {
            "recipe_id": recipe_id,
            "seger_unified": "",
            "seger_al2o3": None,
            "seger_sio2": None,
            "seger_ro": None,
            "acid_base_ratio": None,
            "acid_base_note": "",
            "seger_detail": "{}",
            "calculated_at": None,
            **detail_info,
        }
    detail_info = _parse_seger_detail(seger.seger_detail)
    return {
        "recipe_id": seger.recipe_id,
        "seger_unified": seger.seger_unified,
        "seger_al2o3": seger.seger_al2o3,
        "seger_sio2": seger.seger_sio2,
        "seger_ro": seger.seger_ro,
        "acid_base_ratio": seger.acid_base_ratio,
        "acid_base_note": seger.acid_base_note,
        "seger_detail": seger.seger_detail,
        "calculated_at": seger.calculated_at.isoformat() if seger.calculated_at else None,
        **detail_info,
    }

