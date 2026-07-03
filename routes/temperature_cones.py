"""奥尔顿测温锥温度对照表 - 路由"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from database import get_db
from models import TemperatureCone

router = APIRouter(prefix="/temperature-cones", tags=["测温锥温度表"])


@router.get("")
def list_cones(
    q: str = Query("", description="搜索关键词"),
    page_size: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """获取测温锥列表，支持搜索"""
    query = db.query(TemperatureCone)
    if q:
        keyword = f"%{q}%"
        query = query.filter(
            or_(
                TemperatureCone.cone_no.ilike(keyword),
            )
        )
    total = query.count()
    items = query.order_by(TemperatureCone.sort_order, TemperatureCone.id).limit(page_size).all()
    return {
        "items": [
            {
                "id": c.id,
                "cone_no": c.cone_no,
                "temp_60c": c.temp_60c,
                "temp_108f": c.temp_108f,
                "temp_150c": c.temp_150c,
                "temp_270f": c.temp_270f,
            }
            for c in items
        ],
        "total": total,
    }
