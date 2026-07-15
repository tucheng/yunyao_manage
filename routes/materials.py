import math
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session
from database import get_db
from auth_utils import current_user
from models import Material, MaterialSubstitution, UserMaterial
from services.material_similarity import (
    TOP_SIMILAR_MATERIALS,
    material_similarity,
)

router = APIRouter(prefix="/materials", tags=["材料库"])

MOLECULE_FLOAT_FIELDS = (
    "sio2", "al2o3", "fe2o3", "tio2", "cao", "mgo", "na2o", "k2o",
    "zno", "b2o3", "p2o5", "li2o", "mno2", "coo", "sno2", "cuo",
    "cr2o3", "pbo", "bao", "sro", "loi", "thermal_expansion",
)
MOLECULE_TEXT_FIELDS = ("name_en", "formula", "molecular_weight", "category")


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


def _catalog_payload(material: Material) -> dict:
    return {
        "id": material.id,
        "name": material.name,
        "name_en": material.name_en or "",
        "source": material.source or "",
        "source_id": material.source_id,
        "formula": material.formula or "",
        "molecular_weight": material.molecular_weight or "",
        "category": material.category or "",
        "is_analysis": bool(material.is_analysis),
        "is_primitive": bool(material.is_primitive),
        "sio2": material.sio2,
        "al2o3": material.al2o3,
        "fe2o3": material.fe2o3,
        "tio2": material.tio2,
        "cao": material.cao,
        "mgo": material.mgo,
        "na2o": material.na2o,
        "k2o": material.k2o,
        "zno": material.zno,
        "b2o3": material.b2o3,
        "p2o5": material.p2o5,
        "li2o": material.li2o,
        "mno2": material.mno2,
        "coo": material.coo,
        "sno2": material.sno2,
        "cuo": material.cuo,
        "cr2o3": material.cr2o3,
        "pbo": material.pbo,
        "bao": material.bao,
        "sro": material.sro,
        "loi": material.loi,
        "thermal_expansion": material.thermal_expansion,
    }


def _request_user_id(request: Request) -> int:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="请先登录")
    return user_id


def _normalized_material_name(name: str) -> str:
    """Compare material names after removing every Unicode whitespace character."""
    return re.sub(r"\s+", "", str(name or ""))


def _material_name_conflict(db: Session, name: str, exclude_id: int | None = None) -> Material | None:
    normalized = _normalized_material_name(name)
    if not normalized:
        return None
    query = db.query(Material)
    if exclude_id is not None:
        query = query.filter(Material.id != exclude_id)
    for material in query.all():
        if _normalized_material_name(material.name) == normalized:
            return material
    return None


def _clean_molecule_data(data: dict, *, partial: bool = False) -> dict:
    cleaned = {}
    if not partial or "name" in data:
        name = str(data.get("name", "")).strip()
        if not _normalized_material_name(name):
            raise HTTPException(status_code=400, detail="材料名不能为空")
        if len(name) > 200:
            raise HTTPException(status_code=400, detail="材料名不能超过200个字符")
        cleaned["name"] = name

    max_lengths = {"name_en": 200, "formula": 200, "molecular_weight": 50, "category": 50}
    for field in MOLECULE_TEXT_FIELDS:
        if field not in data:
            continue
        value = str(data.get(field) or "").strip()
        if len(value) > max_lengths[field]:
            raise HTTPException(status_code=400, detail=f"{field}内容过长")
        cleaned[field] = value

    for field in MOLECULE_FLOAT_FIELDS:
        if field not in data:
            continue
        raw = data.get(field)
        if raw in (None, ""):
            cleaned[field] = None
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"{field}必须是数字")
        if not math.isfinite(value):
            raise HTTPException(status_code=400, detail=f"{field}必须是有效数字")
        if field != "thermal_expansion" and not 0 <= value <= 100:
            raise HTTPException(status_code=400, detail=f"{field}必须在0到100之间")
        cleaned[field] = value
    return cleaned


@router.get("/molecules", dependencies=[Depends(current_user)])
def list_my_material_molecules(
    request: Request,
    q: str = Query(""),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """List only material molecule records maintained by the signed-in user."""
    user_id = _request_user_id(request)
    query = db.query(Material).filter(Material.user_id == user_id)
    if q:
        keyword = f"%{q.strip()}%"
        query = query.filter(or_(Material.name.ilike(keyword), Material.name_en.ilike(keyword)))
    total = query.count()
    items = (
        query.order_by(Material.sort_order, Material.name, Material.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "items": [_catalog_payload(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/molecules", dependencies=[Depends(current_user)])
def create_material_molecule(data: dict, request: Request, db: Session = Depends(get_db)):
    user_id = _request_user_id(request)
    cleaned = _clean_molecule_data(data)
    if _material_name_conflict(db, cleaned["name"]):
        raise HTTPException(status_code=409, detail="材料名已存在（忽略空白后不可重名）")
    material = Material(
        user_id=user_id,
        source="user",
        source_id=None,
        is_analysis=1,
        is_primitive=0,
        **cleaned,
    )
    db.add(material)
    db.commit()
    db.refresh(material)
    return _catalog_payload(material)


@router.put("/molecules/{material_id}", dependencies=[Depends(current_user)])
def update_material_molecule(
    material_id: int,
    data: dict,
    request: Request,
    db: Session = Depends(get_db),
):
    user_id = _request_user_id(request)
    material = db.query(Material).filter(
        Material.id == material_id,
        Material.user_id == user_id,
    ).first()
    if not material:
        raise HTTPException(status_code=404, detail="材料不存在或无权修改")
    cleaned = _clean_molecule_data(data, partial=True)
    if "name" in cleaned and _material_name_conflict(db, cleaned["name"], exclude_id=material.id):
        raise HTTPException(status_code=409, detail="材料名已存在（忽略空白后不可重名）")
    for field, value in cleaned.items():
        setattr(material, field, value)
    db.commit()
    db.refresh(material)
    return _catalog_payload(material)


@router.delete("/molecules/{material_id}", dependencies=[Depends(current_user)])
def delete_material_molecule(material_id: int, request: Request, db: Session = Depends(get_db)):
    user_id = _request_user_id(request)
    material = db.query(Material).filter(
        Material.id == material_id,
        Material.user_id == user_id,
    ).first()
    if not material:
        raise HTTPException(status_code=404, detail="材料不存在或无权删除")
    is_referenced = db.query(MaterialSubstitution.id).filter(or_(
        MaterialSubstitution.source_material_id == material.id,
        MaterialSubstitution.target_material_id == material.id,
    )).first()
    if is_referenced:
        raise HTTPException(status_code=409, detail="该材料已有关联相似品数据，暂不能删除")
    db.delete(material)
    db.commit()
    return {"message": "已删除"}


@router.get("/catalog")
def list_material_catalog(
    q: str = Query("", description="搜索中文名、英文名或分子式"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """从合并后的 materials 表查询统一原材料目录。"""
    query = db.query(Material)
    if q:
        keyword = f"%{q}%"
        query = query.filter(
            or_(
                Material.name.ilike(keyword),
                Material.name_en.ilike(keyword),
                Material.formula.ilike(keyword),
            )
        )
    total = query.count()
    source_order = case((Material.source == "local", 0), else_=1)
    items = (
        query.order_by(source_order, Material.sort_order, Material.name)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "items": [_catalog_payload(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/catalog/{material_id}")
def get_material_catalog_item(material_id: int, db: Session = Depends(get_db)):
    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        raise HTTPException(status_code=404, detail="材料不存在")
    return _catalog_payload(material)


@router.get("", dependencies=[Depends(current_user)])
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


@router.get("/categories", dependencies=[Depends(current_user)])
def list_categories(user_id: int = Query(...), db: Session = Depends(get_db)):
    rows = db.query(UserMaterial.category, func.count(UserMaterial.id)).filter(
        UserMaterial.user_id == user_id,
    ).group_by(UserMaterial.category).all()
    return [{"name": r[0] or "未分类", "count": r[1]} for r in rows]


@router.post("", dependencies=[Depends(current_user)])
def add_material(data: dict, user_id: int = Query(...), db: Session = Depends(get_db)):
    name = data.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="材料名不能为空")
    if _find_user_material(db, user_id, name):
        raise HTTPException(status_code=400, detail="材料已存在")
    item, _ = _put_material_in_status(db, user_id, name, data.get("status", "owned"), data)
    db.commit()
    return {"message": "添加成功", "id": item.id}


@router.post("/batch", dependencies=[Depends(current_user)])
def batch_add_materials(data: dict, user_id: int = Query(...), db: Session = Depends(get_db)):
    names = data.get("names", [])
    if not isinstance(names, list) or not names:
        raise HTTPException(status_code=400, detail="请提供材料名称")
    added = 0
    for raw_name in names[:100]:
        name = str(raw_name or "").strip()
        if not name:
            continue
        _, changed = _put_material_in_status(db, user_id, name, "owned", {})
        if changed:
            added += 1
    db.commit()
    return {"message": f"已添加 {added} 种材料", "added": added}


@router.post("/reorder", dependencies=[Depends(current_user)])
def reorder_materials(data: dict, user_id: int = Query(...), db: Session = Depends(get_db)):
    ids = data.get("ids", [])
    for index, item_id in enumerate(ids):
        db.query(UserMaterial).filter(
            UserMaterial.id == item_id,
            UserMaterial.user_id == user_id,
            UserMaterial.status == "owned",
        ).update({"sort_order": index})
    db.commit()
    return {"message": "排序已更新"}


@router.put("/{item_id}", dependencies=[Depends(current_user)])
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


@router.delete("/{item_id}", dependencies=[Depends(current_user)])
def delete_material(item_id: int, user_id: int = Query(...), db: Session = Depends(get_db)):
    item = db.query(UserMaterial).filter(
        UserMaterial.id == item_id, UserMaterial.user_id == user_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="材料不存在")
    db.delete(item)
    db.commit()
    return {"message": "已删除"}


@router.post("/batch_delete", dependencies=[Depends(current_user)])
def batch_delete(data: dict, user_id: int = Query(...), db: Session = Depends(get_db)):
    ids = data.get("ids", [])
    if not ids:
        raise HTTPException(status_code=400, detail="请选择要删除的材料")
    deleted = db.query(UserMaterial).filter(
        UserMaterial.id.in_(ids), UserMaterial.user_id == user_id,
    ).delete(synchronize_session=False)
    db.commit()
    return {"message": f"已删除 {deleted} 种材料"}


@router.post("/wishlist", dependencies=[Depends(current_user)])
def add_to_wishlist(data: dict, user_id: int = Query(...), db: Session = Depends(get_db)):
    name = data.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="材料名不能为空")
    _, changed = _put_material_in_status(db, user_id, name, "wishlist", data)
    if not changed:
        raise HTTPException(status_code=400, detail="已在待购清单中")
    db.commit()
    return {"message": "已加入待购清单", "id": _.id}


@router.get("/wishlist", dependencies=[Depends(current_user)])
def list_wishlist(user_id: int = Query(...), db: Session = Depends(get_db)):
    items = db.query(UserMaterial).filter(
        UserMaterial.user_id == user_id,
        UserMaterial.status == "wishlist",
    ).order_by(UserMaterial.sort_order, UserMaterial.id).all()
    return {"total": len(items), "data": [
        {"id": item.id, "name": item.name, "status": item.status,
         "category": item.category or "", "sort_order": item.sort_order,
         "from_recipe_id": item.from_recipe_id}
        for item in items
    ]}


@router.delete("/wishlist/{item_id}", dependencies=[Depends(current_user)])
def delete_wishlist_item(item_id: int, user_id: int = Query(...), db: Session = Depends(get_db)):
    item = db.query(UserMaterial).filter(
        UserMaterial.id == item_id,
        UserMaterial.user_id == user_id,
        UserMaterial.status == "wishlist",
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="待购材料不存在")
    db.delete(item)
    db.commit()
    return {"message": "已删除"}


@router.post("/wishlist/batch", dependencies=[Depends(current_user)])
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


@router.post("/wishlist/move/{item_id}", dependencies=[Depends(current_user)])
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


@router.post("/move_to_wishlist/{item_id}", dependencies=[Depends(current_user)])
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


@router.post("/wishlist/reorder", dependencies=[Depends(current_user)])
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


# ===== 材料相似关系 =====


@router.get("/{material_id}/substitutions")
def get_substitutions(material_id: int, db: Session = Depends(get_db)) -> list:
    """实时计算某材料的相似品，避免使用旧相似度缓存。"""
    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        raise HTTPException(status_code=404, detail="材料不存在")

    candidates = db.query(Material).filter(Material.id != material_id).all()
    ranked = []
    for target in candidates:
        score = material_similarity(material, target)
        if score > 0:
            ranked.append((score, target))
    ranked.sort(key=lambda item: (-item[0], item[1].name or "", item[1].id))

    result = []
    for score, target in ranked[:TOP_SIMILAR_MATERIALS]:
        result.append({
            "id": target.id,
            "source_material_id": material.id,
            "target_material_id": target.id,
            "target_name": target.name,
            "target_name_en": target.name_en or "",
            "target_source": target.source or "",
            "target_formula": target.formula or "",
            "similarity_score": score,
            "note": "",
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
