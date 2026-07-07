"""Glazy 海外材料 - 公开查询路由"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from database import get_db
from models import GlazyMaterial

router = APIRouter(prefix="/glazy-materials", tags=["附属-海外材料"])


@router.get("")
def list_glazy_materials(
    q: str = Query("", description="搜索关键词（英文名/中文名）"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    """获取 Glazy 海外材料列表，支持搜索"""
    query = db.query(GlazyMaterial)
    if q:
        keyword = f"%{q}%"
        query = query.filter(
            or_(
                GlazyMaterial.name.ilike(keyword),
                GlazyMaterial.name_cn.ilike(keyword),
            )
        )
    total = query.count()
    items = query.order_by(GlazyMaterial.name).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "items": [
            {
                "glazy_id": m.glazy_id,
                "name": m.name,
                "name_cn": m.name_cn or "",
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
    m = db.query(GlazyMaterial).filter(GlazyMaterial.glazy_id == glazy_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="材料不存在")
    return {
        "glazy_id": m.glazy_id,
        "name": m.name,
        "name_cn": m.name_cn or "",
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
