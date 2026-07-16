import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from auth_utils import current_user
from database import get_db
from models import Favorite, Like, Recipe, RecipeView, User
from services.recipe_access import require_recipe_reader
from routes.notifications import add_notification

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
    recipe = _accessible_recipe(db, recipe_id, request)
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
    actor = db.query(User).filter(User.id == user_id).first()
    actor_name = (actor.nickname or actor.username) if actor else f"用户{user_id}"
    add_notification(
        db, user_id=recipe.user_id, from_user_id=user_id, type="favorite",
        recipe_id=recipe_id, content=f"{actor_name} 收藏了你的配方",
    )
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
    actor = db.query(User).filter(User.id == user_id).first()
    actor_name = (actor.nickname or actor.username) if actor else f"用户{user_id}"
    add_notification(
        db, user_id=recipe.user_id, from_user_id=user_id, type="like",
        recipe_id=recipe_id, content=f"{actor_name} 点赞了你的配方",
    )
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
