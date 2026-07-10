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
        if "category" in data:
            existing.category = data["category"]
        return existing, True
    item = UserMaterial(
        user_id=user_id, name=name, status=status,
        sort_order=_next_order(db, user_id, status),
        category=data.get("category", ""),
        from_recipe_id=data.get("from_recipe_id"),
    )
    db.add(item)
    return item, True


@router.get("")
def list_materials(
    user_id: int = Query(...),
    status: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    q = db.query(UserMaterial).filter(UserMaterial.user_id == user_id)
    if status:
        q = q.filter(UserMaterial.status == status)
    if category:
        q = q.filter(UserMaterial.category == category)
    if search:
        q = q.filter(UserMaterial.name.like(f"%{search}%"))

    total = q.count()
    items = (
        q.order_by(UserMaterial.sort_order, UserMaterial.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {"total": total, "page": page, "page_size": page_size, "data": [
        {"id": m.id, "name": m.name, "status": m.status, "category": m.category or "",
         "sort_order": m.sort_order, "from_recipe_id": m.from_recipe_id}
        for m in items
    ]}


@router.get("/categories")
def list_categories(user_id: int = Query(...), db: Session = Depends(get_db)):
    rows = db.query(UserMaterial.category, func.count(UserMaterial.id)).filter(
        UserMaterial.user_id == user_id,
    ).group_by(UserMaterial.category).all()
    return [{"name": r[0] or "未分类", "count": r[1]} for r in rows]


@router.post("")
def add_material(data: dict, user_id: int = Query(...), db: Session = Depends(get_db)):
    name = data.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="材料名不能为空")
    if _find_user_material(db, user_id, name):
        raise HTTPException(status_code=400, detail="材料已存在")
    item, _ = _put_material_in_status(db, user_id, name, data.get("status", "owned"), data)
    db.commit()
    return {"message": "添加成功", "id": item.id}


@router.put("/{item_id}")
def update_material(item_id: int, data: dict, user_id: int = Query(...), db: Session = Depends(get_db)):
    item = db.query(UserMaterial).filter(
        UserMaterial.id == item_id, UserMaterial.user_id == user_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="材料不存在")
    if "name" in data:
        name = data["name"].strip()
        if not name:
            raise HTTPException(status_code=400, detail="材料名不能为空")
        dup = _find_user_material(db, user_id, name)
        if dup and dup.id != item.id:
            raise HTTPException(status_code=400, detail="同名材料已存在")
        item.name = name
    if "status" in data:
        item.status = data["status"]
    if "category" in data:
        item.category = data.get("category", "")
    if "sort_order" in data:
        item.sort_order = data["sort_order"]
    db.commit()
    return {"message": "更新成功", "id": item.id}


@router.delete("/{item_id}")
def delete_material(item_id: int, user_id: int = Query(...), db: Session = Depends(get_db)):
    item = db.query(UserMaterial).filter(
        UserMaterial.id == item_id, UserMaterial.user_id == user_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="材料不存在")
    db.delete(item)
    db.commit()
    return {"message": "已删除"}


@router.post("/batch_delete")
def batch_delete(data: dict, user_id: int = Query(...), db: Session = Depends(get_db)):
    ids = data.get("ids", [])
    if not ids:
        raise HTTPException(status_code=400, detail="请选择要删除的材料")
    deleted = db.query(UserMaterial).filter(
        UserMaterial.id.in_(ids), UserMaterial.user_id == user_id,
    ).delete(synchronize_session=False)
    db.commit()
    return {"message": f"已删除 {deleted} 种材料"}


@router.post("/wishlist")
def add_to_wishlist(data: dict, user_id: int = Query(...), db: Session = Depends(get_db)):
    name = data.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="材料名不能为空")
    _, changed = _put_material_in_status(db, user_id, name, "wishlist", data)
    if not changed:
        raise HTTPException(status_code=400, detail="已在待购清单中")
    db.commit()
    return {"message": "已加入待购清单", "id": _.id}


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


# ===== 材料替换关联 =====


@router.get("/{material_id}/substitutions")
def get_substitutions(material_id: int, db: Session = Depends(get_db)) -> list:
    """获取某材料的替换建议（按相似度降序）"""
    from models import Material, MaterialSubstitution

    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        raise HTTPException(status_code=404, detail="材料不存在")

    subs = (
        db.query(MaterialSubstitution)
        .filter(MaterialSubstitution.source_material_id == material_id)
        .order_by(MaterialSubstitution.similarity_score.desc())
        .all()
    )

    result = []
    for s in subs:
        target = db.query(Material).filter(Material.id == s.target_material_id).first()
        if not target:
            continue
        result.append({
            "id": s.id,
            "source_material_id": s.source_material_id,
            "target_material_id": s.target_material_id,
            "target_name": target.name,
            "target_name_en": target.name_en or "",
            "target_source": target.source or "",
            "target_formula": target.formula or "",
            "similarity_score": s.similarity_score,
            "status": s.status,
            "note": s.note or "",
            # 目标材料氧化物成分
            "sio2": target.sio2, "al2o3": target.al2o3,
            "fe2o3": target.fe2o3, "tio2": target.tio2,
            "cao": target.cao, "mgo": target.mgo,
            "na2o": target.na2o, "k2o": target.k2o,
            "zno": target.zno, "b2o3": target.b2o3,
            "p2o5": target.p2o5, "li2o": target.li2o,
            "mno2": target.mno2, "coo": target.coo,
            "sno2": target.sno2, "cuo": target.cuo,
            "cr2o3": target.cr2o3, "pbo": target.pbo,
            "bao": target.bao, "sro": target.sro,
            "loi": target.loi,
        })

    return result


@router.patch("/substitutions/{sub_id}")
def update_substitution(sub_id: int, data: dict, db: Session = Depends(get_db)):
    """更新替换关联状态（confirmed/ignored）或备注"""
    from models import MaterialSubstitution

    sub = db.query(MaterialSubstitution).filter(MaterialSubstitution.id == sub_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="替换关联不存在")

    if "status" in data:
        sub.status = data["status"]
    if "note" in data:
        sub.note = data["note"]
    db.commit()
    return {"message": "更新成功", "id": sub.id, "status": sub.status}
