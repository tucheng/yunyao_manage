from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import UserMaterial


def next_order(db: Session, user_id: int, status: str) -> int:
    maximum = db.query(func.max(UserMaterial.sort_order)).filter(
        UserMaterial.user_id == user_id,
        UserMaterial.status == status,
    ).scalar() or 0
    return maximum + 1


def find_user_material(db: Session, user_id: int, name: str):
    return db.query(UserMaterial).filter(
        UserMaterial.user_id == user_id,
        UserMaterial.name == name,
    ).first()


def dedupe_user_materials(db: Session, user_id: int) -> None:
    items = db.query(UserMaterial).filter(
        UserMaterial.user_id == user_id,
    ).order_by(UserMaterial.id).all()
    seen = {}
    changed = False
    for item in items:
        key = item.name.strip().lower()
        if not key:
            db.delete(item)
            changed = True
            continue
        existing = seen.get(key)
        if not existing:
            seen[key] = item
            continue
        existing.status = item.status
        existing.sort_order = item.sort_order
        existing.category = item.category or existing.category
        existing.from_recipe_id = item.from_recipe_id or existing.from_recipe_id
        db.delete(item)
        changed = True
    if changed:
        db.commit()


def put_material_in_status(
    db: Session,
    user_id: int,
    name: str,
    status: str,
    data: Optional[dict] = None,
):
    data = data or {}
    existing = find_user_material(db, user_id, name)
    if existing:
        if existing.status == status:
            return existing, False
        existing.status = status
        existing.sort_order = next_order(db, user_id, status)
        if "category" in data:
            existing.category = data["category"]
        return existing, True
    item = UserMaterial(
        user_id=user_id,
        name=name,
        status=status,
        sort_order=next_order(db, user_id, status),
        category=data.get("category", ""),
        from_recipe_id=data.get("from_recipe_id"),
    )
    db.add(item)
    return item, True
