from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from database import get_db
from models import UserMaterial

router = APIRouter(prefix="/materials", tags=["材料库"])


def _next_order(db: Session, user_id: int, status: str) -> int:
    max_order = db.query(func.max(UserMaterial.sort_order)).filter(
        UserMaterial.user_id == user_id,
        UserMaterial.status == status,
    ).scalar() or 0
    return max_order + 1


def _find_user_material(db: Session, user_id: int, name: str):
    return db.query(UserMaterial).filter(
        UserMaterial.user_id == user_id,
        UserMaterial.name == name,
    ).first()


def _dedupe_user_materials(db: Session, user_id: int):
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


def _put_material_in_status(db: Session, user_id: int, name: str, status: str, data: Optional[dict] = None):
    data = data or {}
    existing = _find_user_material(db, user_id, name)
    if existing:
        if existing.status == status:
            return existing, False
        existing.status = status
        existing.sort_order = _next_order(db, user_id, status)
        if status == "wishlist":
            existing.from_recipe_id = data.get("from_recipe_id")
        if status == "owned":
            existing.category = data.get("category", existing.category)
        return existing, True

    item = UserMaterial(
        user_id=user_id,
        name=name,
        category=data.get("category", ""),
        status=status,
        sort_order=_next_order(db, user_id, status),
        from_recipe_id=data.get("from_recipe_id"),
    )
    db.add(item)
    return item, True


@router.get("")
@router.get("/")
def list_materials(user_id: int = Query(...), db: Session = Depends(get_db)):
    _dedupe_user_materials(db, user_id)
    materials = db.query(UserMaterial).filter(
        UserMaterial.user_id == user_id,
        UserMaterial.status == "owned",
    ).order_by(UserMaterial.sort_order, UserMaterial.name).all()
    return materials


@router.post("")
@router.post("/")
def add_material(data: dict, user_id: int = Query(...), db: Session = Depends(get_db)):
    name = data.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="材料名称不能为空")
    item, changed = _put_material_in_status(db, user_id, name, "owned", data)
    if not changed:
        raise HTTPException(status_code=400, detail="该材料已在库中")
    db.commit()
    return {"message": "添加成功", "id": item.id}


@router.post("/batch")
def batch_add(data: dict, user_id: int = Query(...), db: Session = Depends(get_db)):
    names = data.get("names", [])
    added = 0
    for name in names:
        name = name.strip()
        if not name:
            continue
        _, changed = _put_material_in_status(db, user_id, name, "owned", {})
        if changed:
            added += 1
    db.commit()
    return {"message": f"添加了 {added} 种材料"}


@router.post("/reorder")
def reorder_materials(data: dict, user_id: int = Query(...), db: Session = Depends(get_db)):
    ids = data.get("ids", [])
    for i, mid in enumerate(ids):
        db.query(UserMaterial).filter(
            UserMaterial.id == mid,
            UserMaterial.user_id == user_id,
            UserMaterial.status == "owned",
        ).update({"sort_order": i})
    db.commit()
    return {"message": "排序已更新"}


@router.delete("/wishlist/{item_id}")
def delete_wishlist(item_id: int, user_id: int = Query(...), db: Session = Depends(get_db)):
    m = db.query(UserMaterial).filter(
        UserMaterial.id == item_id,
        UserMaterial.user_id == user_id,
        UserMaterial.status == "wishlist",
    ).first()
    if not m:
        raise HTTPException(status_code=404, detail="待购材料不存在")
    db.delete(m)
    db.commit()
    return {"message": "已移除"}


@router.delete("/{material_id}")
def delete_material(material_id: int, user_id: int = Query(...), db: Session = Depends(get_db)):
    m = db.query(UserMaterial).filter(
        UserMaterial.id == material_id,
        UserMaterial.user_id == user_id,
    ).first()
    if not m:
        raise HTTPException(status_code=404, detail="材料不存在")
    db.delete(m)
    db.commit()
    return {"message": "已删除"}


# ===== 待购清单（与材料库同表，status='wishlist'）=====

@router.get("/wishlist")
def list_wishlist(user_id: int = Query(...), db: Session = Depends(get_db)):
    _dedupe_user_materials(db, user_id)
    items = db.query(UserMaterial).filter(
        UserMaterial.user_id == user_id,
        UserMaterial.status == "wishlist",
    ).order_by(UserMaterial.sort_order, UserMaterial.created_at.desc()).all()
    return items


@router.post("/wishlist")
def add_wishlist(data: dict, user_id: int = Query(...), db: Session = Depends(get_db)):
    name = data.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="材料名称不能为空")
    item, changed = _put_material_in_status(db, user_id, name, "wishlist", data)
    if not changed:
        raise HTTPException(status_code=400, detail="已在待购清单中")
    db.commit()
    return {"message": "已加入待购清单", "id": item.id}


@router.post("/wishlist/batch")
def batch_add_wishlist(data: dict, user_id: int = Query(...), db: Session = Depends(get_db)):
    names = data.get("names", [])
    from_recipe_id = data.get("from_recipe_id")
    added = 0
    for name in names:
        name = name.strip()
        if not name: continue
        _, changed = _put_material_in_status(db, user_id, name, "wishlist", {"from_recipe_id": from_recipe_id})
        if changed:
            added += 1
    db.commit()
    return {"message": f"已添加 {added} 种材料到待购清单"}


@router.post("/wishlist/move/{item_id}")
def move_to_materials(item_id: int, user_id: int = Query(...), db: Session = Depends(get_db)):
    wm = db.query(UserMaterial).filter(
        UserMaterial.id == item_id,
        UserMaterial.user_id == user_id,
        UserMaterial.status == "wishlist",
    ).first()
    if not wm:
        raise HTTPException(status_code=404, detail="待购材料不存在")
    wm.status = "owned"
    wm.sort_order = _next_order(db, user_id, "owned")
    db.commit()
    return {"message": "已移到材料库", "id": wm.id}


@router.post("/move_to_wishlist/{item_id}")
def move_to_wishlist(item_id: int, user_id: int = Query(...), db: Session = Depends(get_db)):
    m = db.query(UserMaterial).filter(
        UserMaterial.id == item_id,
        UserMaterial.user_id == user_id,
        UserMaterial.status == "owned",
    ).first()
    if not m:
        raise HTTPException(status_code=404, detail="材料不存在")
    m.status = "wishlist"
    m.sort_order = _next_order(db, user_id, "wishlist")
    db.commit()
    return {"message": "已移到待购清单", "id": m.id}


@router.post("/wishlist/reorder")
def reorder_wishlist(data: dict, user_id: int = Query(...), db: Session = Depends(get_db)):
    ids = data.get("ids", [])
    for i, wid in enumerate(ids):
        db.query(UserMaterial).filter(
            UserMaterial.id == wid,
            UserMaterial.user_id == user_id,
            UserMaterial.status == "wishlist",
        ).update({"sort_order": i})
    db.commit()
    return {"message": "排序已更新"}
