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
from services.recipe_access import require_recipe_reader
from color_names import color_name_in_range, get_color_range_config
import json
import logging
from datetime import datetime

logger = logging.getLogger('yunyao')

router = APIRouter(dependencies=[Depends(current_user)])

def _accessible_recipe(db: Session, recipe_id: int, request: Request) -> Recipe:
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="配方不存在")
    require_recipe_reader(
        db,
        recipe,
        getattr(request.state, "user_id", None),
        consume_quota=True,
    )
    return recipe


@router.post("/{recipe_id}/favorite")
def toggle_favorite(recipe_id: int, request: Request, user_id: int = Query(...), db: Session = Depends(get_db)):
    _accessible_recipe(db, recipe_id, request)
    existing = db.query(Favorite).filter(
        Favorite.recipe_id == recipe_id,
        Favorite.user_id == user_id,
    ).first()
    if existing:
        db.delete(existing)
        db.commit()
        return {"favorited": False}
    fav = Favorite(recipe_id=recipe_id, user_id=user_id)
    db.add(fav)
    db.commit()
    return {"favorited": True}


@router.post("/{recipe_id}/like")
def toggle_recipe_like(recipe_id: int, request: Request, user_id: int = Query(...), db: Session = Depends(get_db)):
    recipe = _accessible_recipe(db, recipe_id, request)
    existing = db.query(Like).filter(
        Like.recipe_id == recipe_id,
        Like.user_id == user_id,
    ).first()
    if existing:
        db.delete(existing)
        recipe.likes = max(0, (recipe.likes or 1) - 1)
        db.commit()
        return {"liked": False, "likes": recipe.likes}
    like = Like(recipe_id=recipe_id, user_id=user_id)
    db.add(like)
    recipe.likes = (recipe.likes or 0) + 1
    db.commit()
    return {"liked": True, "likes": recipe.likes}


@router.post("/{recipe_id}/view")
def record_recipe_view(recipe_id: int, request: Request, user_id: int = Query(...), db: Session = Depends(get_db)):
    """记录浏览；同一用户同一配方同一天只消耗一次额度。"""
    from models import UserDailyRecipeView
    from services.user_quota import business_today, quota_status
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    already_viewed = db.query(UserDailyRecipeView.id).filter(
        UserDailyRecipeView.user_id == user_id,
        UserDailyRecipeView.recipe_id == recipe_id,
        UserDailyRecipeView.view_date == business_today(),
    ).first()
    recipe = _accessible_recipe(db, recipe_id, request)
    if recipe.user_id == user_id:
        consumed, remaining = False, None
    else:
        # _accessible_recipe 已按“同用户、同配方、同一天”规则消费额度。
        consumed = already_viewed is None
        remaining = quota_status(db, user)["recipe_view_remaining"]
    existing = db.query(RecipeView).filter(
        RecipeView.recipe_id == recipe_id,
        RecipeView.user_id == user_id,
    ).first()
    if not existing:
        db.add(RecipeView(recipe_id=recipe_id, user_id=user_id))
        db.commit()
    db.commit()
    return {"ok": True, "quota_consumed": consumed, "remaining": remaining}
