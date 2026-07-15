from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from database import get_db
from auth_utils import current_user
from models import UserSettings, FiringCurve
from pydantic import BaseModel
from typing import Optional
import json

router = APIRouter(prefix="/settings", tags=["用户设置"], dependencies=[Depends(current_user)])


class SettingsUpdate(BaseModel):
    materials: Optional[list[str]] = None
    kiln_types: Optional[list[str]] = None
    temperatures: Optional[list[str]] = None
    firing_curve_id: Optional[int] = None
    body_material: Optional[str] = None


@router.get("")
def get_settings(user_id: int = Query(...), db: Session = Depends(get_db)):
    """获取用户默认设置"""
    settings = db.query(UserSettings).filter(UserSettings.user_id == user_id).first()
    if not settings:
        return {
            "materials": [],
            "kiln_types": [],
            "temperatures": [],
            "firing_curve_id": None,
            "body_material": "",
        }

    result = {
        "materials": json.loads(settings.materials or "[]"),
        "kiln_types": json.loads(settings.kiln_types or "[]"),
        "temperatures": json.loads(settings.temperatures or "[]"),
        "firing_curve_id": settings.firing_curve_id,
        "body_material": settings.body_material or "",
    }
    return result


@router.put("")
def update_settings(
    body: SettingsUpdate,
    user_id: int = Query(...),
    db: Session = Depends(get_db),
):
    """更新用户默认设置"""
    settings = db.query(UserSettings).filter(UserSettings.user_id == user_id).first()
    if not settings:
        settings = UserSettings(user_id=user_id)
        db.add(settings)

    if body.materials is not None:
        settings.materials = json.dumps(body.materials, ensure_ascii=False)
    if body.kiln_types is not None:
        settings.kiln_types = json.dumps(body.kiln_types, ensure_ascii=False)
    if body.temperatures is not None:
        settings.temperatures = json.dumps(body.temperatures, ensure_ascii=False)
    if body.firing_curve_id is not None:
        if body.firing_curve_id and not db.query(FiringCurve).filter(
            FiringCurve.id == body.firing_curve_id,
            FiringCurve.user_id == user_id,
        ).first():
            raise HTTPException(status_code=400, detail="烧制曲线不存在或不属于当前用户")
        settings.firing_curve_id = body.firing_curve_id or None
    if body.body_material is not None:
        settings.body_material = body.body_material

    db.commit()
    return {"message": "保存成功"}


@router.get("/curves")
def list_curves(user_id: int = Query(...), db: Session = Depends(get_db)):
    """获取当前用户的烧制曲线（供设置页面选择）"""
    curves = db.query(FiringCurve).filter(
        FiringCurve.user_id == user_id,
    ).order_by(FiringCurve.sort_order, FiringCurve.name).all()
    return [
        {
            "id": c.id,
            "name": c.name,
            "type": c.type,
            "target_temp": c.target_temp,
            "description": c.description,
        }
        for c in curves
    ]
