"""材料列表路由（从 materials 表查询，source='local' 优先）"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, case
from database import get_db
from models import Material

router = APIRouter(prefix="/glazy-materials", tags=["附属-原材料"])


@router.get("")
def list_glazy_materials(
    q: str = Query("", description="搜索关键词（英文名/中文名）"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    """获取材料列表，local 优先显示"""
    query = db.query(Material)
    if q:
        keyword = f"%{q}%"
        query = query.filter(
            or_(
                Material.name.ilike(keyword),
                Material.name_en.ilike(keyword),
            )
        )
    total = query.count()
    # source='local' 优先，再按名称排序
    sort_order = case(
        (Material.source == "local", 0),
        else_=1
    )
    items = query.order_by(sort_order, Material.name).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "items": [
            {
                "glazy_id": m.source_id if m.source == "glazy" else m.id,
                "name": m.name_en or m.name,
                "name_cn": m.name or "",
                "source": m.source,
                "is_primitive": bool(m.is_primitive),
                "sio2": m.sio2,
                "al2o3": m.al2o3,
                "na2o": m.na2o,
                "k2o": m.k2o,
                "mgo": m.mgo,
                "cao": m.cao,
                "fe2o3": m.fe2o3,
                "tio2": m.tio2,
                "zno": m.zno,
                "b2o3": m.b2o3,
                "p2o5": m.p2o5,
                "loi": m.loi,
                "thermal_expansion": m.thermal_expansion,
            }
            for m in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{glazy_id}")
def get_glazy_material(glazy_id: int, db: Session = Depends(get_db)):
    """获取单个材料详情"""
    m = db.query(Material).filter(
        Material.source == "glazy",
        Material.source_id == glazy_id,
    ).first()
    if not m:
        raise HTTPException(status_code=404, detail="材料不存在")
    return {
        "glazy_id": m.source_id,
        "name": m.name_en,
        "name_cn": m.name or "",
        "is_primitive": bool(m.is_primitive),
        "sio2": m.sio2,
        "al2o3": m.al2o3,
        "na2o": m.na2o,
        "k2o": m.k2o,
        "mgo": m.mgo,
        "cao": m.cao,
        "fe2o3": m.fe2o3,
        "tio2": m.tio2,
        "zno": m.zno,
        "b2o3": m.b2o3,
        "p2o5": m.p2o5,
        "loi": m.loi,
        "thermal_expansion": m.thermal_expansion,
    }
