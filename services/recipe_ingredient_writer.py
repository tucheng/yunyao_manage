from sqlalchemy.orm import Session

from models import IngredientName, Recipe, RecipeIngredient
from security import encrypt, hash_for_lookup
from services.material_analysis import resolve_recipe_ingredients


def replace_recipe_ingredients(
    db: Session,
    recipe: Recipe,
    ingredients: list[dict],
    *,
    created_from: str | None = None,
) -> dict:
    db.query(RecipeIngredient).filter(RecipeIngredient.recipe_id == recipe.id).delete()
    public_names = set()
    for index, item in enumerate(ingredients):
        raw_name = str(item.get("name") or "").strip()
        if not raw_name:
            continue
        public_names.add(raw_name)
        db.add(RecipeIngredient(
            recipe_id=recipe.id,
            recipe_no=recipe.recipe_no or "",
            name=encrypt(raw_name),
            name_en=str(item.get("name_en") or "").strip(),
            name_hash=hash_for_lookup(raw_name),
            amount=encrypt(str(item.get("amount") or "").strip()),
            unit=str(item.get("unit") or "").strip()[:20],
            note=item.get("note") or "",
            is_additional=1 if item.get("is_additional") else 0,
            sort_order=item.get("sort_order", index),
        ))
    db.flush()
    existing_names = {
        row[0] for row in db.query(IngredientName.name).filter(IngredientName.name.in_(public_names)).all()
    } if public_names else set()
    for name in public_names - existing_names:
        db.add(IngredientName(name=name))
    db.flush()
    return resolve_recipe_ingredients(
        db,
        recipe.id,
        owner_user_id=recipe.user_id,
        created_from=created_from or recipe.source or "frontend",
        create_missing=True,
    )
