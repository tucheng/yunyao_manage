from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session, joinedload
from database import get_db
from models import AppSetting, Recipe, User, Review, Favorite, Work, RecipeSequence, Like, RecipeView, RecipeIngredient, IngredientName, RecipeSeger, RecipeVersion
from schemas import (
    RecipeCreate, RecipeUpdate, RecipeOut, RecipeListItem,
    ReviewCreate, ReviewOut,
)
from security import encrypt, decrypt, hash_for_lookup
from image_utils import normalize_image_url, parse_image_list, serialize_image_list
from auth_utils import user_id_from_request
from sqlalchemy import func
from seger_calculator import calculate_seger
from services.recipe_version import snapshot_recipe
from color_names import color_name_in_range, get_color_range_config
import json
import logging
from datetime import datetime

logger = logging.getLogger('yunyao')

router = APIRouter()

from services.recipe_number import generate_recipe_no

@router.post("/init-sequence")
def init_recipe_sequence(db: Session = Depends(get_db)):
    """初始化编号计数器"""
    existing = db.query(RecipeSequence).first()
    if existing:
        return {"message": f"计数器已存在，当前：{existing.letter}{existing.counter:0{existing.digits}d}，位数：{existing.digits}"}
    db.add(RecipeSequence(letter="A", counter=0, digits=3))
    db.commit()
    return {"message": "已初始化，起始编号 A001"}

