from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from database import get_db
from auth_utils import user_id_from_request
from models import Purchase, RecipeIngredient, Recipe
from schemas import RecipeIngredientOut

router = APIRouter(prefix="/recipe-ingredients", tags=["配方配料"])


@router.get("/{recipe_id}", response_model=list[RecipeIngredientOut])
def get_ingredients(recipe_id: int, request: Request, db: Session = Depends(get_db)):
    """获取配方的配料列表"""
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="配方不存在")

    current_user_id = user_id_from_request(request)
    is_owner = bool(current_user_id and recipe.user_id == current_user_id)

    if recipe.visibility == "private" and not is_owner:
        raise HTTPException(status_code=404, detail="配方不存在")

    if recipe.visibility in ("paid", "showoff") and not is_owner:
        if not current_user_id:
            return []
        purchase = db.query(Purchase).filter(
            Purchase.recipe_id == recipe_id,
            Purchase.buyer_id == current_user_id,
            Purchase.status == "confirmed",
        ).first()
        if not purchase:
            return []

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
    request: Request,
    db: Session = Depends(get_db),
):
    """批量保存配料（全量替换）"""
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="配方不存在")

    # 校验当前用户是否为配方作者
    current_user_id = getattr(request.state, "user_id", None)
    if not current_user_id or recipe.user_id != current_user_id:
        raise HTTPException(status_code=403, detail="无权修改此配方的配料")

    # 删除旧的
    db.query(RecipeIngredient).filter(RecipeIngredient.recipe_id == recipe_id).delete()

    # 插入新的
    for i, item in enumerate(ingredients):
        ing = RecipeIngredient(
            recipe_id=recipe_id,
            recipe_no=recipe.recipe_no or "",
            name=(item.get("name") or "").strip(),
            name_en=(item.get("name_en") or "").strip(),
            amount=str(item.get("amount") or "").strip(),
            unit=str(item.get("unit") or "").strip()[:20],
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
