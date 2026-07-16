import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from auth_utils import current_user
from database import get_db
from models import Recipe, Review, User
from schemas import ReviewCreate, ReviewOut
from services.recipe_access import require_recipe_reader
from services.recipe_serializers import review_payload, user_names
from routes.notifications import add_notification

logger = logging.getLogger('yunyao')

router = APIRouter()


def _user_names(user: User | None) -> dict[str, str]:
    """Compatibility wrapper for callers that import the legacy route helper."""
    return user_names(user)


def _require_reviewable_recipe(db: Session, recipe_id: int, request: Request) -> Recipe:
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="配方不存在")
    require_recipe_reader(
        db,
        recipe,
        getattr(request.state, "user_id", None),
        consume_quota=True,
    )
    return recipe


@router.post("/review", dependencies=[Depends(current_user)])
def create_review(body: ReviewCreate, request: Request, user_id: int = Query(...), db: Session = Depends(get_db)):
    recipe = _require_reviewable_recipe(db, body.recipe_id, request)
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
    target_user_id = parent.user_id if parent else recipe.user_id
    actor_name = (user.nickname or user.username) if user else f"用户{user_id}"
    add_notification(
        db, user_id=target_user_id, from_user_id=user_id, type="comment",
        recipe_id=body.recipe_id,
        content=f"{actor_name} {'回复了你的评论' if parent else '评论了你的配方'}",
    )
    return review_payload(review, user)


@router.get("/{recipe_id}/reviews", response_model=list[ReviewOut], dependencies=[Depends(current_user)])
def list_reviews(recipe_id: int, request: Request, db: Session = Depends(get_db)):
    _require_reviewable_recipe(db, recipe_id, request)
    db.commit()
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
        reply_map[pid].append(review_payload(reply, reply_user))

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
        result.append(review_payload(
            r,
            user,
            recipe_title=recipe.title if recipe else "",
            replies=reply_map.get(r.id, []),
        ))

    return result
