from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text, func
from sqlalchemy.orm import Session
from database import get_db
from auth_utils import user_id_from_request
from models import Purchase, RecipeIngredient, Recipe, IngredientName, Material
from schemas import RecipeIngredientOut
from security import encrypt, decrypt, hash_for_lookup
from seger_calculator import calculate_seger
import logging

logger = logging.getLogger('yunyao')

router = APIRouter(prefix="/recipe-ingredients", tags=["配方配料"])


@router.get("/{recipe_id}", response_model=list[RecipeIngredientOut])
def get_ingredients(recipe_id: int, request: Request, db: Session = Depends(get_db)):
    """获取配方的配料列表（解密后返回）"""
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

    rows = (
        db.query(RecipeIngredient)
        .filter(RecipeIngredient.recipe_id == recipe_id)
        .order_by(RecipeIngredient.sort_order, RecipeIngredient.id)
        .all()
    )

    # 构建返回对象，逐个解密 name 和 amount
    result = []
    for row in rows:
        decrypted_name = decrypt(row.name)
        # 查找材料库中的匹配ID
        mat = None
        if decrypted_name:
            name_clean = decrypted_name.replace(' ', '')
            mat = (
                db.query(Material)
                .filter(func.replace(Material.name, ' ', '') == name_clean)
                .order_by(Material.source.desc())
                .first()
            )
        result.append(RecipeIngredientOut(
            id=row.id,
            recipe_id=row.recipe_id,
            recipe_no=row.recipe_no,
            name=decrypted_name,
            name_en=row.name_en,
            amount=decrypt(row.amount),
            unit=row.unit,
            note=row.note,
            is_additional=row.is_additional,
            sort_order=row.sort_order,
            material_id=mat.id if mat else None,
        ))
    return result


@router.post("/{recipe_id}", response_model=list[RecipeIngredientOut])
def save_ingredients(
    recipe_id: int,
    ingredients: list[dict],
    request: Request,
    db: Session = Depends(get_db),
):
    """批量保存配料（全量替换，加密存储）"""
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="配方不存在")

    # 校验当前用户是否为配方作者
    current_user_id = getattr(request.state, "user_id", None)
    if not current_user_id or recipe.user_id != current_user_id:
        raise HTTPException(status_code=403, detail="无权修改此配方的配料")

    # 删除旧的
    db.query(RecipeIngredient).filter(RecipeIngredient.recipe_id == recipe_id).delete()

    # 插入新的（加密存储）
    for i, item in enumerate(ingredients):
        raw_name = (item.get("name") or "").strip()
        ing = RecipeIngredient(
            recipe_id=recipe_id,
            recipe_no=recipe.recipe_no or "",
            name=encrypt(raw_name),
            name_en=(item.get("name_en") or "").strip(),
            name_hash=hash_for_lookup(raw_name),
            amount=encrypt(str(item.get("amount") or "").strip()),
            unit=str(item.get("unit") or "").strip()[:20],
            note=item.get("note") or "",
            is_additional=1 if item.get("is_additional") else 0,
            sort_order=item.get("sort_order", i),
        )
        db.add(ing)

    # 同步公开配料名索引
    all_names = set()
    for item in ingredients:
        raw_name = (item.get("name") or "").strip()
        if raw_name:
            all_names.add(raw_name)
    for name in all_names:
        db.execute(text("INSERT IGNORE INTO ingredient_names (name) VALUES (:name)"), {"name": name})

    db.commit()

    # Trigger Seger formula recalculation after ingredients change
    try:
        calculate_seger(recipe_id, db)
        logger.info("Seger recalculation completed for recipe %s after ingredient update", recipe_id)
    except Exception as e:
        logger.error("Seger recalculation failed for recipe %s: %s", recipe_id, e)

    rows = (
        db.query(RecipeIngredient)
        .filter(RecipeIngredient.recipe_id == recipe_id)
        .order_by(RecipeIngredient.sort_order, RecipeIngredient.id)
        .all()
    )

    # 解密后返回
    result = []
    for row in rows:
        result.append(RecipeIngredientOut(
            id=row.id,
            recipe_id=row.recipe_id,
            recipe_no=row.recipe_no,
            name=decrypt(row.name),
            name_en=row.name_en,
            amount=decrypt(row.amount),
            unit=row.unit,
            note=row.note,
            is_additional=row.is_additional,
            sort_order=row.sort_order,
        ))
    return result
