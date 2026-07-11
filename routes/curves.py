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


# ===== 新用户注册默认曲线 =====
DEFAULT_USER_CURVES = [
    {
        "name": "标准瓷器",
        "type": "还原",
        "target_temp": "1280℃",
        "description": "标准瓷器烧制曲线，还原气氛△9-10，适合多数瓷泥和还原釉",
        "segments": json.dumps([
            {"rate": 80, "temp": 600, "hold": 0},
            {"rate": 100, "temp": 900, "hold": 0},
            {"rate": 80, "temp": 1280, "hold": 20},
        ]),
        "sort_order": 0,
    },
    {
        "name": "陶罐",
        "type": "氧化",
        "target_temp": "1050℃",
        "description": "标准陶器烧制曲线，氧化气氛，适合陶泥和低温釉",
        "segments": json.dumps([
            {"rate": 100, "temp": 500, "hold": 0},
            {"rate": 150, "temp": 800, "hold": 0},
            {"rate": 120, "temp": 1050, "hold": 15},
        ]),
        "sort_order": 1,
    },
]


def create_default_user_curves(db: Session, user_id: int):
    """为新用户添加默认烧制曲线"""
    for c in DEFAULT_USER_CURVES:
        curve = FiringCurve(
            user_id=user_id,
            name=c["name"],
            type=c["type"],
            target_temp=c["target_temp"],
            segments=c["segments"],
            description=c["description"],
            sort_order=c["sort_order"],
        )
        db.add(curve)
    db.commit()


@router.get("")
@router.get("/")
def list_curves(user_id: int = Query(...), db: Session = Depends(get_db)):
    """获取某用户的个人烧制曲线"""
    curves = (
        db.query(FiringCurve)
        .filter(FiringCurve.user_id == user_id)
        .order_by(FiringCurve.sort_order, FiringCurve.id)
        .all()
    )
    return curves


@router.get("/{curve_id}")
def get_curve(curve_id: int, user_id: int = Query(...), db: Session = Depends(get_db)):
    curve = db.query(FiringCurve).filter(
        FiringCurve.id == curve_id,
        FiringCurve.user_id == user_id,
    ).first()
    if not curve:
        raise HTTPException(status_code=404, detail="曲线不存在")
    return curve


@router.post("")
@router.post("/")
def create_curve(data: CurveCreate, user_id: int = Query(...), db: Session = Depends(get_db)):
    curve = FiringCurve(
        user_id=user_id,
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
def update_curve(curve_id: int, data: CurveUpdate, user_id: int = Query(...), db: Session = Depends(get_db)):
    curve = db.query(FiringCurve).filter(
        FiringCurve.id == curve_id,
        FiringCurve.user_id == user_id,
    ).first()
    if not curve:
        raise HTTPException(status_code=404, detail="曲线不存在或无权修改")
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(curve, key, value)
    db.commit()
    db.refresh(curve)
    return curve


@router.post("/{curve_id}/copy")
def copy_curve(curve_id: int, user_id: int = Query(...), db: Session = Depends(get_db)):
    """复制一条曲线到当前用户（来源可以是系统默认或用户自己的）"""
    original = db.query(FiringCurve).filter(FiringCurve.id == curve_id).first()
    if not original:
        raise HTTPException(status_code=404, detail="原曲线不存在")
    new_curve = FiringCurve(
        user_id=user_id,
        name=original.name + " (副本)",
        type=original.type,
        target_temp=original.target_temp,
        segments=original.segments,
        description=original.description,
        sort_order=original.sort_order,
    )
    db.add(new_curve)
    db.commit()
    db.refresh(new_curve)
    return new_curve


@router.delete("/{curve_id}")
def delete_curve(curve_id: int, user_id: int = Query(...), db: Session = Depends(get_db)):
    curve = db.query(FiringCurve).filter(
        FiringCurve.id == curve_id,
        FiringCurve.user_id == user_id,
    ).first()
    if not curve:
        raise HTTPException(status_code=404, detail="曲线不存在或无权删除")
    db.delete(curve)
    db.commit()
    return {"message": "已删除"}
