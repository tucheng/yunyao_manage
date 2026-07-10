"""配方版本快照服务"""
import json
from datetime import datetime
from sqlalchemy import func
from models import Recipe, RecipeIngredient, RecipeSeger, RecipeVersion
from security import decrypt


def snapshot_recipe(recipe_id: int, db, note: str = "", user_id: int = 0):
    """保存当前配方快照到 recipe_versions"""
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        return
    ingredients = db.query(RecipeIngredient).filter(
        RecipeIngredient.recipe_id == recipe_id
    ).order_by(RecipeIngredient.sort_order, RecipeIngredient.id).all()
    seger = db.query(RecipeSeger).filter(RecipeSeger.recipe_id == recipe_id).first()

    # 构建 recipe_data
    recipe_data = {c.name: getattr(recipe, c.name) for c in recipe.__table__.columns}
    recipe_data.pop("id", None)
    for k, v in list(recipe_data.items()):
        if isinstance(v, datetime):
            recipe_data[k] = v.isoformat()

    ingredients_data = []
    for ing in ingredients:
        ingredients_data.append({
            "name": decrypt(ing.name),
            "name_en": ing.name_en,
            "amount": decrypt(ing.amount) if ing.amount else "",
            "unit": ing.unit,
            "note": ing.note,
            "is_additional": ing.is_additional,
            "sort_order": ing.sort_order,
        })

    seger_data = None
    if seger:
        seger_data = {c.name: getattr(seger, c.name) for c in seger.__table__.columns}
        for k in ("id", "recipe_id"):
            seger_data.pop(k, None)
        for k, v in list(seger_data.items()):
            if isinstance(v, datetime):
                seger_data[k] = v.isoformat()

    # 版本号自增
    last = db.query(func.max(RecipeVersion.version_no)).filter(
        RecipeVersion.recipe_id == recipe_id
    ).scalar()
    version_no = (last or 0) + 1

    version = RecipeVersion(
        recipe_id=recipe_id,
        version_no=version_no,
        recipe_data=json.dumps(recipe_data, ensure_ascii=False, default=str),
        ingredients_data=json.dumps(ingredients_data, ensure_ascii=False),
        seger_data=json.dumps(seger_data, ensure_ascii=False, default=str) if seger_data else None,
        note=note,
        created_by=user_id or None,
    )
    db.add(version)
    db.flush()
