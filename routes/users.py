from fastapi import APIRouter, Depends, HTTPException, Query, Body, Request
from sqlalchemy.orm import Session
from auth_utils import get_current_user
from database import get_db
from encryption_utils import encrypt, decrypt, hash_for_lookup
from models import User, UserLevel, Recipe, Work, Follow, Favorite, FiringCurve, ToBeFired
from auth_utils import get_current_user
from models import AppSetting
import json

PAID_ENABLED_KEY = "paid_enabled"


def _get_paid_enabled(db: Session) -> bool:
    row = db.query(AppSetting).filter(AppSetting.key == PAID_ENABLED_KEY).first()
    if not row or not row.value:
        return False
    try:
        return json.loads(row.value) is True
    except Exception:
        return False

router = APIRouter(prefix="/users", tags=["用户"])


@router.get("/profile")
def get_profile(user_id: int = Query(...), db: Session = Depends(get_db)):
    """获取用户个人信息 + 统计数据"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 统计
    following_count = db.query(Follow).filter(Follow.follower_id == user_id).count()
    follower_count = db.query(Follow).filter(Follow.followed_id == user_id).count()
    recipe_count = db.query(Recipe).filter(Recipe.user_id == user_id).count()
    work_count = db.query(Work).filter(Work.user_id == user_id).count()
    fav_count = db.query(Favorite).filter(Favorite.user_id == user_id).count()
    # 被收藏数：当前用户的作品/配方被他人收藏的数量
    from sqlalchemy import or_
    my_recipe_ids = [r.id for r in db.query(Recipe.id).filter(Recipe.user_id == user_id).all()]
    my_work_ids = [w.id for w in db.query(Work.id).filter(Work.user_id == user_id).all()]
    collected_count = db.query(Favorite).filter(
        or_(
            Favorite.recipe_id.in_(my_recipe_ids),
            Favorite.work_id.in_(my_work_ids),
        )
    ).count()
    curve_count = db.query(FiringCurve).filter(FiringCurve.id > 0).count()
    to_fire_count = db.query(ToBeFired).filter(
        ToBeFired.user_id == user_id,
        ToBeFired.status == "pending",
    ).count()

    # 获取等级信息
    level = db.query(UserLevel).filter(
        UserLevel.id == (user.level_id or 1)
    ).first()

    return {
        "id": user.id,
        "username": user.username or "",
        "nickname": user.nickname or "",
        "avatar": user.avatar or "",
        "bio": user.bio or "",
        "gender": user.gender or "",
        "birthday": user.birthday or "",
        "location": user.location or "",
        "level_id": user.level_id or 1,
        "level_name": level.name if level else "普通用户",
        "can_publish_paid": level.can_publish_paid if level else False,
        "paid_enabled": _get_paid_enabled(db),
        "following_count": following_count,
        "follower_count": follower_count,
        "recipe_count": recipe_count,
        "work_count": work_count,
        "favorite_count": fav_count,
        "collected_count": collected_count,
        "curve_count": curve_count,
        "to_fire_count": to_fire_count,
        "created_at": user.created_at,
    }


@router.get("/me")
def get_my_profile(request: Request, db: Session = Depends(get_db)):
    """获取当前登录用户的完整信息（含手机号/邮箱/余额等敏感字段）"""
    user = get_current_user(request, db)

    level = db.query(UserLevel).filter(
        UserLevel.id == (user.level_id or 1)
    ).first()

    return {
        "id": user.id,
        "username": user.username or "",
        "nickname": user.nickname or "",
        "avatar": user.avatar or "",
        "bio": user.bio or "",
        "gender": user.gender or "",
        "birthday": user.birthday or "",
        "location": user.location or "",
        "phone": decrypt(user.phone or "") or "",
        "email": decrypt(user.email or "") or "",
        "balance": user.balance or 0,
        "level_id": user.level_id or 1,
        "level_name": level.name if level else "普通用户",
        "can_publish_paid": level.can_publish_paid if level else False,
        "paid_enabled": _get_paid_enabled(db),
        "created_at": user.created_at,
    }


@router.put("/profile")
def update_profile(
    request: Request,
    data: dict = Body({}),
    db: Session = Depends(get_db),
):
    """更新个人信息（昵称/头像/简介/手机号/邮箱等）"""
    user = get_current_user(request, db)

    if data is None:
        data = {}

    nickname = data.get("nickname")
    avatar = data.get("avatar")
    bio = data.get("bio")
    phone = data.get("phone")
    email = data.get("email")

    if nickname is not None:
        user.nickname = nickname.strip()[:50] or user.nickname
    if avatar is not None:
        user.avatar = avatar.strip()[:200]
    if bio is not None:
        user.bio = bio.strip()[:500]
    if phone is not None:
        phone_val = phone.strip()
        if phone_val:
            existing = User.by_phone(db, phone_val)
            if existing and existing.id != user.id:
                raise HTTPException(status_code=400, detail="该手机号已被其他账号绑定")
            user.phone = encrypt(phone_val)
            user.phone_hash = hash_for_lookup(phone_val)
        else:
            user.phone = None
            user.phone_hash = None
    if email is not None:
        email_val = email.strip()
        if email_val:
            existing = User.by_email(db, email_val)
            if existing and existing.id != user.id:
                raise HTTPException(status_code=400, detail="该邮箱已被其他账号绑定")
            user.email = encrypt(email_val)
            user.email_hash = hash_for_lookup(email_val)
        else:
            user.email = None
            user.email_hash = None

    gender = data.get("gender")
    if gender is not None:
        user.gender = gender.strip()[:10]
    birthday = data.get("birthday")
    if birthday is not None:
        user.birthday = birthday.strip()[:20]
    location = data.get("location")
    if location is not None:
        user.location = location.strip()[:100]

    db.commit()
    db.refresh(user)
    return {
        "message": "更新成功",
        "nickname": user.nickname,
        "avatar": user.avatar,
        "bio": user.bio,
        "gender": user.gender or "",
        "birthday": user.birthday or "",
        "location": user.location or "",
        "phone": decrypt(user.phone or "") or "",
        "email": decrypt(user.email or "") or "",
    }


# ========= 待烧（ToBeFired） =========


@router.get("/to-be-fired")
def list_to_be_fired(
    user_id: int = Query(...),
    page: int = 1,
    page_size: int = Query(default=20, alias="page_size"),
    db: Session = Depends(get_db),
):
    """获取我的待烧列表"""
    query = db.query(ToBeFired).filter(ToBeFired.user_id == user_id)

    total = query.count()
    items = (
        query.order_by(ToBeFired.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    result = []
    for item in items:
        recipe = None
        if item.recipe_id:
            recipe = db.query(Recipe).filter(Recipe.id == item.recipe_id).first()
        result.append({
            "id": item.id,
            "recipe_id": item.recipe_id,
            "recipe_title": recipe.title if recipe else "",
            "recipe_type": recipe.type if recipe else "",
            "note": item.note or "",
            "status": item.status,
            "created_at": item.created_at,
        })

    return {
        "total": total,
        "items": result,
        "page": page,
        "page_size": page_size,
    }


@router.post("/to-be-fired")
def add_to_be_fired(
    user_id: int = Query(...),
    data: dict = Body(...),
    db: Session = Depends(get_db),
):
    """添加到待烧"""
    recipe_id = data.get("recipe_id")
    note = (data.get("note") or "").strip()

    if not recipe_id:
        raise HTTPException(status_code=400, detail="请指定配方")

    # 检查是否已存在
    existing = db.query(ToBeFired).filter(
        ToBeFired.user_id == user_id,
        ToBeFired.recipe_id == recipe_id,
        ToBeFired.status == "pending",
    ).first()
    if existing:
        return {"message": "已在待烧列表中", "id": existing.id}

    item = ToBeFired(
        user_id=user_id,
        recipe_id=recipe_id,
        note=note,
        status="pending",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"message": "已加入待烧", "id": item.id}


@router.delete("/to-be-fired/{item_id}")
def remove_to_be_fired(
    item_id: int,
    user_id: int = Query(...),
    db: Session = Depends(get_db),
):
    """从待烧移除"""
    item = db.query(ToBeFired).filter(
        ToBeFired.id == item_id,
        ToBeFired.user_id == user_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="待烧记录不存在")
    db.delete(item)
    db.commit()
    return {"message": "已移除"}


@router.put("/to-be-fired/{item_id}")
def update_to_be_fired(
    item_id: int,
    user_id: int = Query(...),
    data: dict = Body({}),
    db: Session = Depends(get_db),
):
    """更新待烧状态/备注"""
    item = db.query(ToBeFired).filter(
        ToBeFired.id == item_id,
        ToBeFired.user_id == user_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="待烧记录不存在")

    if "status" in data and data["status"] in ("pending", "firing", "done"):
        item.status = data["status"]
    if "note" in data:
        item.note = (data["note"] or "").strip()[:200]

    db.commit()
    return {"message": "更新成功", "status": item.status, "note": item.note}
