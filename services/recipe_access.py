"""Shared authorization rules for reading and linking recipes."""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import Recipe, User


def require_recipe_reader(
    db: Session,
    recipe: Recipe,
    user_id: int | None,
    *,
    consume_quota: bool = False,
) -> User:
    if not user_id:
        raise HTTPException(status_code=401, detail="请先登录")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    if recipe.visibility not in ("public", "showoff") and recipe.user_id != user.id:
        raise HTTPException(status_code=404, detail="配方不存在")
    if consume_quota and recipe.user_id != user.id:
        from services.user_quota import consume_recipe_view_once

        consume_recipe_view_once(db, user, recipe.id)
    return user


def require_recipe_owner(recipe: Recipe, user_id: int | None) -> None:
    if not user_id:
        raise HTTPException(status_code=401, detail="请先登录")
    if recipe.user_id != user_id:
        raise HTTPException(status_code=404, detail="配方不存在")
