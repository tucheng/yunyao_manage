import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from auth_utils import current_user
from database import get_db
from models import Favorite, Recipe, User, Work
from schemas import RecipeListItem
from services.recipe_queries import _first_work_image
from services.recipe_serializers import favorite_recipe_payload, favorite_work_payload

logger = logging.getLogger('yunyao')

router = APIRouter()

@router.get("/feed/following", response_model=list[RecipeListItem], dependencies=[Depends(current_user)])
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

@router.get("/mine", response_model=list[RecipeListItem], dependencies=[Depends(current_user)])
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



@router.get("/favorites", dependencies=[Depends(current_user)])
def favorite_recipes(
    user_id: int = Query(...),
    page: int = 1,
    page_size: int = Query(default=20, alias="page_size"),
    db: Session = Depends(get_db),
):
    # 私密配方改为不可见后，不再通过收藏列表、总数或分页位置泄露。
    visible_favorites = (
        db.query(Favorite)
        .outerjoin(Recipe, Favorite.recipe_id == Recipe.id)
        .filter(
            Favorite.user_id == user_id,
            or_(
                Favorite.recipe_id.is_(None),
                Recipe.visibility.in_(("public", "showoff")),
                Recipe.user_id == user_id,
            ),
        )
    )
    total = visible_favorites.count()
    favs = (
        visible_favorites
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
            if recipe and (recipe.visibility in ("public", "showoff") or recipe.user_id == user_id):
                user = db.query(User).filter(User.id == recipe.user_id).first()
                result.append(favorite_recipe_payload(recipe, user))
        if f.work_id:
            wid = f.work_id
            work = db.query(Work).filter(Work.id == wid).first()
            if work:
                user = db.query(User).filter(User.id == work.user_id).first()
                result.append(favorite_work_payload(work, user))
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
