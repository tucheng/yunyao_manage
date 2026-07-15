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
from auth_utils import current_user, user_id_from_request
from sqlalchemy import func
from seger_calculator import calculate_seger
from services.recipe_version import snapshot_recipe
from color_names import color_name_in_range, get_color_range_config
import json
import logging
from datetime import datetime

logger = logging.getLogger('yunyao')

router = APIRouter()

@router.post("/review", dependencies=[Depends(current_user)])
def create_review(body: ReviewCreate, user_id: int = Query(...), db: Session = Depends(get_db)):
    # 如果是回复，验证父评论存在
    parent = None
    if body.parent_id:
        parent = db.query(Review).filter(Review.id == body.parent_id).first()
        if not parent:
            raise HTTPException(status_code=404, detail="回复的评论不存在")
        if parent.recipe_id != body.recipe_id:
            raise HTTPException(status_code=400, detail="不能回复其他配方的评论")

    review = Review(
        parent_id=body.parent_id if body.parent_id > 0 else None,
        recipe_id=body.recipe_id,
        user_id=user_id,
        rating=body.rating,
        content=body.content,
        image=body.image,
        body_material=body.body_material,
        kiln_type=body.kiln_type,
        kiln_type_other=body.kiln_type_other,
        temperature=body.temperature,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    user = db.query(User).filter(User.id == review.user_id).first()
    return {
        "id": review.id,
        "parent_id": review.parent_id,
        "user_id": review.user_id,
        "recipe_id": review.recipe_id,
        "rating": review.rating,
        "content": review.content or "",
        "image": review.image or "",
        "body_material": review.body_material or "",
        "kiln_type": review.kiln_type or "",
        "kiln_type_other": review.kiln_type_other or "",
        "temperature": review.temperature or "",
        "created_at": review.created_at,
        "nickname": user.nickname if user else f"用户{review.user_id}",
        "replies": [],
    }


@router.get("/{recipe_id}/reviews", response_model=list[ReviewOut])
def list_reviews(recipe_id: int, db: Session = Depends(get_db)):
    # 手动查所有回复，按 parent_id 分组
    all_replies = db.query(Review).filter(
        Review.recipe_id == recipe_id,
        Review.parent_id.isnot(None),
    ).all()
    reply_map = {}
    for reply in all_replies:
        pid = reply.parent_id
        if pid not in reply_map:
            reply_map[pid] = []
        reply_user = db.query(User).filter(User.id == reply.user_id).first()
        reply_map[pid].append({
            "id": reply.id,
            "parent_id": reply.parent_id,
            "user_id": reply.user_id,
            "recipe_id": reply.recipe_id,
            "rating": reply.rating,
            "content": reply.content or "",
            "image": reply.image or "",
            "body_material": reply.body_material or "",
            "kiln_type": reply.kiln_type or "",
            "kiln_type_other": reply.kiln_type_other or "",
            "temperature": reply.temperature or "",
            "created_at": reply.created_at,
            "nickname": reply_user.nickname if reply_user else f"用户{reply.user_id}",
            "replies": [],
        })

    # 只取顶级评论
    reviews = (
        db.query(Review)
        .filter(Review.recipe_id == recipe_id, Review.parent_id.is_(None))
        .order_by(Review.created_at.desc())
        .all()
    )

    result = []
    for r in reviews:
        user = db.query(User).filter(User.id == r.user_id).first()
        recipe = db.query(Recipe).filter(Recipe.id == r.recipe_id).first()
        result.append({
            "id": r.id,
            "parent_id": r.parent_id,
            "user_id": r.user_id,
            "recipe_id": r.recipe_id,
            "rating": r.rating,
            "content": r.content or "",
            "image": r.image or "",
            "body_material": r.body_material or "",
            "kiln_type": r.kiln_type or "",
            "kiln_type_other": r.kiln_type_other or "",
            "temperature": r.temperature or "",
            "created_at": r.created_at,
            "nickname": user.nickname if user else f"用户{r.user_id}",
            "recipe_title": recipe.title if recipe else "",
            "replies": reply_map.get(r.id, []),
        })

    return result
