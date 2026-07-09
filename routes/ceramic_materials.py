"""本土原材料 - 路由（从 materials 表查询 source='local'）"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from database import get_db
from models import Material

router = APIRouter(prefix="/ceramic-materials", tags=["本土原材料清单"])


@router.get("")
def list_materials(
    q: str = Query("", description="搜索关键词"),
    page_size: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """获取本土原材料列表，支持搜索"""
    query = db.query(Material).filter(Material.source == "local")
    if q:
        keyword = f"%{q}%"
        query = query.filter(
            or_(
                Material.name.ilike(keyword),
                Material.formula.ilike(keyword),
            )
        )
    total = query.count()
    items = query.order_by(Material.sort_order, Material.id).limit(page_size).all()
    return {
        "items": [
            {
                "id": m.id,
                "name": m.name,
                "formula": m.formula,
                "molecular_weight": m.molecular_weight,
                "category": m.category,
            }
            for m in items
        ],
        "total": total,
    }


@router.get("/{item_id}")
def get_material(item_id: int, db: Session = Depends(get_db)):
    item = db.query(Material).filter(Material.id == item_id, Material.source == "local").first()
    if not item:
        raise HTTPException(status_code=404, detail="材料不存在")
    return {
        "id": item.id,
        "name": item.name,
        "formula": item.formula,
        "molecular_weight": item.molecular_weight,
        "category": item.category,
    }
