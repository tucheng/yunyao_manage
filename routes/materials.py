from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session
from database import get_db
from auth_utils import current_user
from models import Material, MaterialSubstitution, RecipeIngredient, UserMaterial
from services.material_similarity import (
    TOP_SIMILAR_MATERIALS,
    material_similarity,
)
from services.material_catalog import (
    catalog_payload as _catalog_payload,
    clean_molecule_data as _clean_molecule_data,
    material_name_conflict as _material_name_conflict,
    request_user_id as _request_user_id,
)
from services.user_materials import (
    find_user_material as _find_user_material,
    next_order as _next_order,
    put_material_in_status as _put_material_in_status,
)
from services.material_analysis import prepare_material

router = APIRouter(prefix="/materials", tags=["材料库"])

OXIDE_FIELDS = (
    "sio2", "al2o3", "fe2o3", "tio2", "cao", "mgo", "na2o", "k2o",
    "zno", "b2o3", "p2o5", "li2o", "mno2", "coo", "sno2", "cuo",
    "cr2o3", "pbo", "bao", "sro",
)


def _has_oxide_data(values) -> bool:
    """Only a positive oxide percentage counts as usable molecule data."""
    get_value = values.get if isinstance(values, dict) else lambda field: getattr(values, field, None)
    for field in OXIDE_FIELDS:
        try:
            if float(get_value(field) or 0) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _molecule_payload(db: Session, material: Material) -> dict:
    result = _catalog_payload(material)
    result["affected_recipe_count"] = db.query(func.count(func.distinct(RecipeIngredient.recipe_id))).filter(
        RecipeIngredient.material_id == material.id,
    ).scalar() or 0
    return result



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
        "items": [_molecule_payload(db, item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/molecules", dependencies=[Depends(current_user)])
def create_material_molecule(data: dict, request: Request, db: Session = Depends(get_db)):
    user_id = _request_user_id(request)
    cleaned = _clean_molecule_data(data)
    if not _has_oxide_data(cleaned):
        raise HTTPException(status_code=400, detail="至少填写一种有效氧化物后才能保存")
    if _material_name_conflict(db, cleaned["name"], cleaned.get("name_en", "")):
        raise HTTPException(status_code=409, detail="中英文材料名组合已存在（忽略空白）")
    material = Material(
        user_id=user_id,
        source="user",
        source_id=None,
        is_analysis=1,
        is_primitive=0,
        status="initial",
        created_from="frontend",
        **cleaned,
    )
    db.add(material)
    db.flush()
    prepare_material(db, material)
    db.commit()
    db.refresh(material)
    return _molecule_payload(db, material)


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
    if material.status == "submitted":
        raise HTTPException(status_code=409, detail="材料正在等待管理员审核，暂不能修改")
    cleaned = _clean_molecule_data(data, partial=True)
    final_name = cleaned.get("name", material.name)
    final_name_en = cleaned.get("name_en", material.name_en or "")
    if _material_name_conflict(db, final_name, final_name_en, exclude_id=material.id):
        raise HTTPException(status_code=409, detail="中英文材料名组合已存在（忽略空白）")
    for field, value in cleaned.items():
        setattr(material, field, value)
    if not _has_oxide_data(material):
        raise HTTPException(status_code=400, detail="至少填写一种有效氧化物后才能保存")
    prepare_material(db, material)
    material.status = "modified"
    material.submitted_at = None
    material.review_note = None
    db.commit()
    db.refresh(material)
    return _molecule_payload(db, material)


@router.post("/molecules/{material_id}/submit", dependencies=[Depends(current_user)])
def submit_material_molecule(material_id: int, request: Request, db: Session = Depends(get_db)):
    user_id = _request_user_id(request)
    material = db.query(Material).filter(Material.id == material_id, Material.user_id == user_id).first()
    if not material:
        raise HTTPException(status_code=404, detail="材料不存在或无权提交")
    if material.status not in ("initial", "modified"):
        raise HTTPException(status_code=409, detail="当前状态不能重复提交")
    if not _has_oxide_data(material):
        raise HTTPException(status_code=400, detail="至少填写一种有效氧化物后才能提交")
    material.status = "submitted"
    material.submitted_at = datetime.now(timezone.utc)
    material.review_note = None
    db.commit()
    return {"message": "已提交管理员审核", "id": material.id, "status": material.status}


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
    if db.query(RecipeIngredient.id).filter(RecipeIngredient.material_id == material.id).first():
        raise HTTPException(status_code=409, detail="该材料已被配方使用，不能删除")
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
    query = db.query(Material).filter(Material.is_active.is_(True))
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
