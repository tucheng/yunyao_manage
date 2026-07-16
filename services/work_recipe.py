from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import Recipe, Work
from services.recipe_access import require_recipe_reader


def recipe_for_work_link(db: Session, recipe_id, user_id: int) -> Recipe | None:
    if recipe_id in (None, "", 0, "0"):
        return None
    try:
        normalized_id = int(recipe_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="配方编号无效") from exc
    recipe = db.query(Recipe).filter(Recipe.id == normalized_id).with_for_update().first()
    if not recipe:
        raise HTTPException(status_code=404, detail="配方不存在")
    # Linking a recipe only exposes its public card metadata. It is not a
    # recipe-detail view, so keep the visibility check without consuming the
    # user's recipe-view quota.
    require_recipe_reader(db, recipe, user_id, consume_quota=False)
    return recipe


def set_work_recipe(db: Session, work: Work, recipe_id, user_id: int) -> None:
    new_recipe = recipe_for_work_link(db, recipe_id, user_id)
    new_recipe_id = new_recipe.id if new_recipe else None
    if work.recipe_id == new_recipe_id:
        return
    if work.recipe_id:
        old_recipe = db.query(Recipe).filter(Recipe.id == work.recipe_id).with_for_update().first()
        if old_recipe:
            old_recipe.work_count = max(0, (old_recipe.work_count or 0) - 1)
    work.recipe_id = new_recipe_id
    if new_recipe:
        new_recipe.work_count = (new_recipe.work_count or 0) + 1
