import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from auth_utils import current_user
from database import get_db
from models import RecipeSequence

logger = logging.getLogger('yunyao')

router = APIRouter(dependencies=[Depends(current_user)])

@router.post("/init-sequence")
def init_recipe_sequence(db: Session = Depends(get_db)):
    """初始化编号计数器"""
    existing = db.query(RecipeSequence).first()
    if existing:
        return {"message": f"计数器已存在，当前：{existing.letter}{existing.counter:0{existing.digits}d}，位数：{existing.digits}"}
    db.add(RecipeSequence(letter="A", counter=0, digits=3))
    db.commit()
    return {"message": "已初始化，起始编号 A001"}
