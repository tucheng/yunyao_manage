from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from database import get_db
from models import FiringCurve
from pydantic import BaseModel
from typing import Optional
import json

router = APIRouter(prefix="/curves", tags=["烧制曲线"])


class CurveCreate(BaseModel):
    name: str
    type: str = "氧化"
    target_temp: str = ""
    segments: str = "[]"
    description: str = ""
    sort_order: int = 0


class CurveUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    target_temp: Optional[str] = None
    segments: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None


# 预置的常用烧制曲线
DEFAULT_CURVES = [
    {
        "name": "标准氧化 1220℃",
        "type": "氧化",
        "target_temp": "1220℃",
        "description": "电窑常用标准曲线，氧化气氛，适合多数中温釉",
        "segments": json.dumps([
            {"rate": 100, "temp": 600, "hold": 0},
            {"rate": 150, "temp": 1000, "hold": 0},
            {"rate": 120, "temp": 1220, "hold": 15},
        ]),
        "sort_order": 1,
    },
    {
        "name": "标准还原 1280℃",
        "type": "还原",
        "target_temp": "1280℃",
        "description": "气窑还原曲线，△9-10，适合还原釉和瓷泥烧成",
        "segments": json.dumps([
            {"rate": 80, "temp": 600, "hold": 0},
            {"rate": 100, "temp": 900, "hold": 0},
            {"rate": 80, "temp": 1280, "hold": 20},
        ]),
        "sort_order": 2,
    },
    {
        "name": "中温氧化 1240℃",
        "type": "氧化",
        "target_temp": "1240℃",
        "description": "偏高温度段氧化曲线，适合某些特殊釉面效果",
        "segments": json.dumps([
            {"rate": 100, "temp": 600, "hold": 0},
            {"rate": 130, "temp": 1000, "hold": 0},
            {"rate": 100, "temp": 1240, "hold": 15},
        ]),
        "sort_order": 3,
    },
    {
        "name": "低温氧化 1050℃",
        "type": "氧化",
        "target_temp": "1050℃",
        "description": "低温段曲线，适合低温釉和二次烧成",
        "segments": json.dumps([
            {"rate": 150, "temp": 600, "hold": 0},
            {"rate": 200, "temp": 1050, "hold": 10},
        ]),
        "sort_order": 4,
    },
    {
        "name": "高温还原 1300℃",
        "type": "还原",
        "target_temp": "1300℃",
        "description": "△11-12 高温还原，适合高温瓷器和特殊还原釉",
        "segments": json.dumps([
            {"rate": 80, "temp": 600, "hold": 0},
            {"rate": 100, "temp": 900, "hold": 0},
            {"rate": 70, "temp": 1300, "hold": 30},
        ]),
        "sort_order": 5,
    },
    {
        "name": "乐烧 1000℃ 快速",
        "type": "氧化",
        "target_temp": "1000℃",
        "description": "乐烧专用快速升温，达到温度后直接取出",
        "segments": json.dumps([
            {"rate": 200, "temp": 600, "hold": 0},
            {"rate": 300, "temp": 1000, "hold": 0},
        ]),
        "sort_order": 6,
    },
]


@router.get("/init")
def init_default_curves(db: Session = Depends(get_db)):
    """初始化预置烧制曲线"""
    count = db.query(FiringCurve).count()
    if count > 0:
        return {"message": f"已有 {count} 条曲线，跳过初始化"}
    for c in DEFAULT_CURVES:
        curve = FiringCurve(
            name=c["name"],
            type=c["type"],
            target_temp=c["target_temp"],
            segments=json.dumps(c["segments"]) if isinstance(c["segments"], list) else c["segments"],
            description=c["description"],
            sort_order=c["sort_order"],
        )
        db.add(curve)
    db.commit()
    return {"message": f"已初始化 {len(DEFAULT_CURVES)} 条默认烧制曲线"}


@router.get("")
@router.get("/")
def list_curves(db: Session = Depends(get_db)):
    curves = db.query(FiringCurve).order_by(FiringCurve.sort_order).all()
    return curves


@router.get("/{curve_id}")
def get_curve(curve_id: int, db: Session = Depends(get_db)):
    curve = db.query(FiringCurve).filter(FiringCurve.id == curve_id).first()
    if not curve:
        raise HTTPException(status_code=404, detail="曲线不存在")
    return curve


@router.post("")
@router.post("/")
def create_curve(data: CurveCreate, db: Session = Depends(get_db)):
    curve = FiringCurve(
        name=data.name,
        type=data.type,
        target_temp=data.target_temp,
        segments=data.segments,
        description=data.description,
        sort_order=data.sort_order,
    )
    db.add(curve)
    db.commit()
    db.refresh(curve)
    return curve


@router.put("/{curve_id}")
def update_curve(curve_id: int, data: CurveUpdate, db: Session = Depends(get_db)):
    curve = db.query(FiringCurve).filter(FiringCurve.id == curve_id).first()
    if not curve:
        raise HTTPException(status_code=404, detail="曲线不存在")
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(curve, key, value)
    db.commit()
    db.refresh(curve)
    return curve


@router.delete("/{curve_id}")
def delete_curve(curve_id: int, db: Session = Depends(get_db)):
    curve = db.query(FiringCurve).filter(FiringCurve.id == curve_id).first()
    if not curve:
        raise HTTPException(status_code=404, detail="曲线不存在")
    db.delete(curve)
    db.commit()
    return {"message": "已删除"}
