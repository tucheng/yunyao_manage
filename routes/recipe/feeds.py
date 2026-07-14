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

router = APIRouter()

from services.recipe_queries import *

@router.get("/feed/following", response_model=list[RecipeListItem])
def following_recipes(
    user_id: int = Query(...),
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    """获取关注用户发布的配方"""
    from models import Follow
    # 找到关注列表
    following = db.query(Follow.followed_id).filter(
        Follow.follower_id == user_id
    ).all()
    followed_ids = [f.followed_id for f in following]
    if not followed_ids:
        return []

    query = db.query(Recipe).filter(
        Recipe.user_id.in_(followed_ids),
        Recipe.visibility.in_(["public", "showoff"]),
    )
    # favorite count subquery
    fav_counts = (
        db.query(Favorite.recipe_id, func.count(Favorite.id).label("fav_count"))
        .filter(Favorite.recipe_id.isnot(None))
        .group_by(Favorite.recipe_id)
        .subquery()
    )
    # latest work per recipe via window function
    subq = (
        db.query(
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
        db.query(
            subq.c.recipe_id,
            subq.c.image,
            subq.c.images,
        )
        .filter(subq.c.rn == 1)
        .subquery()
    )
    rows = (
        query.outerjoin(User, Recipe.user_id == User.id)
        .outerjoin(fav_counts, Recipe.id == fav_counts.c.recipe_id)
        .outerjoin(first_work, Recipe.id == first_work.c.recipe_id)
        .with_entities(Recipe, User.nickname, User.avatar, first_work.c.image, first_work.c.images, fav_counts.c.fav_count)
        .order_by(Recipe.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    result = []
    for r, nickname, avatar, work_img, work_imgs, fav_cnt in rows:
        setattr(r, 'author_name', nickname if nickname else f'用户{r.user_id}')
        setattr(r, 'avatar', avatar or "")
        setattr(r, 'work_image', _first_work_image(work_img or "", work_imgs or ""))
        setattr(r, 'favorite_count', fav_cnt or 0)
        result.append(r)
    return result


# ========= 我的 =========

@router.get("/mine", response_model=list[RecipeListItem])
def my_recipes(user_id: int = Query(...), db: Session = Depends(get_db)):
    recipes = (
        db.query(Recipe)
        .filter(Recipe.user_id == user_id)
        .order_by(Recipe.created_at.desc())
        .all()
    )
    mine = db.query(User).filter(User.id == user_id).first()
    myname = mine.nickname if mine else f"用户{user_id}"
    # 计算每个配方的收藏数
    recipe_ids = [r.id for r in recipes]
    fav_counts = (
        db.query(Favorite.recipe_id, func.count(Favorite.id).label("cnt"))
        .filter(Favorite.recipe_id.in_(recipe_ids))
        .group_by(Favorite.recipe_id)
        .all()
    )
    fav_map = {r.recipe_id: r.cnt for r in fav_counts}
    for r in recipes:
        setattr(r, 'author_name', myname)
        setattr(r, 'favorite_count', fav_map.get(r.id, 0))
    return recipes



@router.get("/favorites")
def favorite_recipes(
    user_id: int = Query(...),
    page: int = 1,
    page_size: int = Query(default=20, alias="page_size"),
    db: Session = Depends(get_db),
):
    # 先查总数
    total = db.query(Favorite).filter(Favorite.user_id == user_id).count()
    favs = (
        db.query(Favorite)
        .filter(Favorite.user_id == user_id)
        .order_by(Favorite.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    result = []
    for f in favs:
        if f.recipe_id:
            rid = f.recipe_id
            recipe = db.query(Recipe).filter(Recipe.id == rid).first()
            if recipe:
                user = db.query(User).filter(User.id == recipe.user_id).first()
                result.append({
                    "id": recipe.id,
                    "user_id": recipe.user_id,
                    "type": "recipe",
                    "title": recipe.title,
                    "recipe_no": recipe.recipe_no or '',
                    "category": recipe.category or '',
                    "cover": normalize_image_url(recipe.cover) or (parse_image_list(recipe.images) or [""])[0],
                    "author_name": user.nickname if user else '',
                    "created_at": recipe.created_at.isoformat() if recipe.created_at else '',
                })
        if f.work_id:
            wid = f.work_id
            work = db.query(Work).filter(Work.id == wid).first()
            if work:
                user = db.query(User).filter(User.id == work.user_id).first()
                result.append({
                    "id": work.id,
                    "user_id": work.user_id,
                    "type": "work",
                    "title": (work.description or '作品').split('\n')[0][:30],
                    "cover": normalize_image_url(work.image),
                    "author_name": user.nickname if user else '',
                    "body_material": work.body_material or '',
                    "created_at": work.created_at.isoformat() if work.created_at else '',
                })
    result.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return {
        "items": result,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ========= 用户信息（含信任分） =========

@router.get("/user/{user_id}")
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {
        "user_id": user.id,
        "nickname": user.nickname,
        "trust_score": user.trust_score or 100,
        "avatar": user.avatar,
    }

