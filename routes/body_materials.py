from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from database import get_db
from models import BodyMaterial
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/materials/body", tags=["坯体料管理"])


class BodyMaterialCreate(BaseModel):
    name: str
    sort_order: int = 0


class BodyMaterialUpdate(BaseModel):
    name: Optional[str] = None
    sort_order: Optional[int] = None


# 预置坯体料
DEFAULT_BODY_MATERIALS = [
    "高白泥", "黑陶泥", "紫砂泥", "瓷泥", "陶泥", "粗陶", "红陶", "瓦胎",
]


@router.get("/init")
def init_default_body_materials(db: Session = Depends(get_db)):
    """初始化预置坯体料"""
    count = db.query(BodyMaterial).count()
    if count > 0:
        return {"message": f"已有 {count} 条坯体料，跳过初始化"}
    for i, name in enumerate(DEFAULT_BODY_MATERIALS):
        mat = BodyMaterial(name=name, sort_order=i)
        db.add(mat)
    db.commit()
    return {"message": f"已初始化 {len(DEFAULT_BODY_MATERIALS)} 种坯体料"}


@router.get("")
@router.get("/")
def list_body_materials(db: Session = Depends(get_db)):
    mats = db.query(BodyMaterial).order_by(BodyMaterial.sort_order).all()
    return mats


@router.post("")
@router.post("/")
def create_body_material(data: BodyMaterialCreate, db: Session = Depends(get_db)):
    existing = db.query(BodyMaterial).filter(BodyMaterial.name == data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="已存在")
    mat = BodyMaterial(name=data.name, sort_order=data.sort_order)
    db.add(mat)
    db.commit()
    db.refresh(mat)
    return mat


@router.put("/{mat_id}")
def update_body_material(mat_id: int, data: BodyMaterialUpdate, db: Session = Depends(get_db)):
    mat = db.query(BodyMaterial).filter(BodyMaterial.id == mat_id).first()
    if not mat:
        raise HTTPException(status_code=404, detail="不存在")
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(mat, key, value)
    db.commit()
    db.refresh(mat)
    return mat


@router.delete("/{mat_id}")
def delete_body_material(mat_id: int, db: Session = Depends(get_db)):
    mat = db.query(BodyMaterial).filter(BodyMaterial.id == mat_id).first()
    if not mat:
        raise HTTPException(status_code=404, detail="不存在")
    db.delete(mat)
    db.commit()
    return {"message": "已删除"}
