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

@router.post("/{recipe_id}/favorite")
def toggle_favorite(recipe_id: int, user_id: int = Query(...), db: Session = Depends(get_db)):
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
def toggle_recipe_like(recipe_id: int, user_id: int = Query(...), db: Session = Depends(get_db)):
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="配方不存在")
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
def record_recipe_view(recipe_id: int, user_id: int = Query(...), db: Session = Depends(get_db)):
    """记录浏览；同一用户同一配方同一天只消耗一次额度。"""
    from services.user_quota import consume_recipe_view_once
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="配方不存在")
    if recipe.user_id == user_id:
        consumed, remaining = False, None
    else:
        consumed, remaining = consume_recipe_view_once(db, user, recipe_id)
    existing = db.query(RecipeView).filter(
        RecipeView.recipe_id == recipe_id,
        RecipeView.user_id == user_id,
    ).first()
    if not existing:
        db.add(RecipeView(recipe_id=recipe_id, user_id=user_id))
        db.commit()
    db.commit()
    return {"ok": True, "quota_consumed": consumed, "remaining": remaining}
