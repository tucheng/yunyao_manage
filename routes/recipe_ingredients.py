from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.orm import Session
from database import get_db
from auth_utils import current_user, user_id_from_request
from models import RecipeIngredient, Recipe, IngredientName, Material, User
from schemas import RecipeIngredientOut
from security import encrypt, decrypt, hash_for_lookup
from seger_calculator import calculate_seger
from services.material_analysis import resolve_material, resolve_recipe_ingredients
import logging

logger = logging.getLogger('yunyao')

router = APIRouter(prefix="/recipe-ingredients", tags=["配方配料"], dependencies=[Depends(current_user)])


@router.get("/{recipe_id}", response_model=list[RecipeIngredientOut])
def get_ingredients(recipe_id: int, request: Request, db: Session = Depends(get_db)):
    """获取配方的配料列表（解密后返回）"""
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="配方不存在")

    current_user_id = user_id_from_request(request)
    if not current_user_id:
        raise HTTPException(status_code=401, detail="请先登录")
    is_owner = bool(current_user_id and recipe.user_id == current_user_id)

    if recipe.visibility not in ("public", "showoff") and not is_owner:
        raise HTTPException(status_code=404, detail="配方不存在")

    if recipe.visibility == "showoff" and not is_owner:
        return []

    if not is_owner:
        from services.user_quota import consume_recipe_view_once
        user = db.query(User).filter(User.id == current_user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        consume_recipe_view_once(db, user, recipe_id)
        db.commit()

    rows = (
        db.query(RecipeIngredient)
        .filter(RecipeIngredient.recipe_id == recipe_id)
        .order_by(RecipeIngredient.sort_order, RecipeIngredient.id)
        .all()
    )

    # 构建返回对象，逐个解密 name 和 amount
    result = []
    for row in rows:
        # Most historical recipe rows predate field encryption. They are
        # still valid application data and are migrated separately; accepting
        # plaintext here keeps reads available without weakening malformed
        # Fernet-token handling in security.decrypt.
        decrypted_name = decrypt(row.name, allow_plaintext=True)
        mat = db.query(Material).filter(Material.id == row.material_id).first() if row.material_id else None
        if not mat and decrypted_name:
            mat, _ = resolve_material(
                db, name=decrypted_name, name_en=row.name_en or "", create_missing=False,
            )
        result.append(RecipeIngredientOut(
            id=row.id,
            recipe_id=row.recipe_id,
            recipe_no=row.recipe_no,
            name=decrypted_name,
            name_en=row.name_en,
            amount=decrypt(row.amount, allow_plaintext=True),
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

    db.flush()
    resolution = resolve_recipe_ingredients(
        db,
        recipe_id,
        owner_user_id=recipe.user_id,
        created_from=recipe.source or "frontend",
        create_missing=True,
    )
    db.commit()
    if resolution["created"]:
        logger.info("Created %s missing materials for recipe %s", len(resolution["created"]), recipe_id)

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
            name=decrypt(row.name, allow_plaintext=True),
            name_en=row.name_en,
            amount=decrypt(row.amount, allow_plaintext=True),
            unit=row.unit,
            note=row.note,
            is_additional=row.is_additional,
            sort_order=row.sort_order,
            material_id=row.material_id,
        ))
    return result
