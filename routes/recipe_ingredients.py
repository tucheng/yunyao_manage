from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from database import get_db
from models import RecipeIngredient, Recipe
from schemas import RecipeIngredientOut

router = APIRouter(prefix="/recipe-ingredients", tags=["配方配料"])


@router.get("/{recipe_id}", response_model=list[RecipeIngredientOut])
def get_ingredients(recipe_id: int, db: Session = Depends(get_db)):
    """获取配方的配料列表"""
    return (
        db.query(RecipeIngredient)
        .filter(RecipeIngredient.recipe_id == recipe_id)
        .order_by(RecipeIngredient.sort_order, RecipeIngredient.id)
        .all()
    )


@router.post("/{recipe_id}", response_model=list[RecipeIngredientOut])
def save_ingredients(
    recipe_id: int,
    ingredients: list[dict],
    db: Session = Depends(get_db),
):
    """批量保存配料（全量替换）"""
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="配方不存在")

    # 删除旧的
    db.query(RecipeIngredient).filter(RecipeIngredient.recipe_id == recipe_id).delete()

    # 插入新的
    for i, item in enumerate(ingredients):
        ing = RecipeIngredient(
            recipe_id=recipe_id,
            recipe_no=recipe.recipe_no or "",
            name=(item.get("name") or "").strip(),
            name_en=(item.get("name_en") or "").strip(),
            amount=(item.get("amount") or "").strip(),
            note=item.get("note") or "",
            is_additional=1 if item.get("is_additional") else 0,
            sort_order=item.get("sort_order", i),
        )
        db.add(ing)

    db.commit()
    return (
        db.query(RecipeIngredient)
        .filter(RecipeIngredient.recipe_id == recipe_id)
        .order_by(RecipeIngredient.sort_order, RecipeIngredient.id)
        .all()
    )
