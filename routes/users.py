from fastapi import APIRouter, Depends, HTTPException, Query, Body, Request
from typing import Optional
from sqlalchemy.orm import Session
from auth_utils import current_user, get_current_user
from database import get_db
from encryption_utils import encrypt, decrypt, hash_for_lookup
from models import User, UserLevel, Recipe, Work, Follow, Favorite, FiringCurve, ToBeFired


def _safe_decrypt(val):
    """安全解密，遇到未加密的明文直接返回原值"""
    if not val:
        return ""
    try:
        return decrypt(val)
    except Exception:
        return val


router = APIRouter(prefix="/users", tags=["用户"])


@router.get("/profile")
def get_profile(request: Request, user_id: int = Query(...), db: Session = Depends(get_db)):
    """获取公开用户资料；仅本人可读取私有统计和账号字段。"""
    viewer = get_current_user(request, db)
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

    result = {
        "id": user.id,
        "nickname": user.nickname or "",
        "avatar": user.avatar or "",
        "bio": user.bio or "",
        "location": user.location or "",
        "level_id": user.level_id or 1,
        "level_name": level.name if level else "普通用户",
        "following_count": following_count,
        "follower_count": follower_count,
        "recipe_count": recipe_count,
        "work_count": work_count,
        "collected_count": collected_count,
        "created_at": user.created_at,
    }
    if viewer.id == user.id:
        result.update({
            "username": user.username or "",
            "gender": user.gender or "",
            "birthday": user.birthday or "",
            "favorite_count": fav_count,
            "curve_count": curve_count,
            "to_fire_count": to_fire_count,
            "expires_at": str(user.expires_at) if user.expires_at else "",
        })
    return result

@router.get("/me", dependencies=[Depends(current_user)])
def get_my_profile(request: Request, db: Session = Depends(get_db)):
    """获取当前登录用户的完整信息。"""
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
        "phone": _safe_decrypt(user.phone),
        "email": _safe_decrypt(user.email),
        "level_id": user.level_id or 1,
        "level_name": level.name if level else "普通用户",
        "created_at": user.created_at,
        "expires_at": str(user.expires_at) if user.expires_at else "",
    }


@router.put("/profile", dependencies=[Depends(current_user)])
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
        "phone": _safe_decrypt(user.phone),
        "email": _safe_decrypt(user.email),
    }


# ========= 发布资格检查 =========


@router.get("/publish-status", dependencies=[Depends(current_user)])
def get_publish_status(user_id: Optional[int] = Query(None), db: Session = Depends(get_db)):
    """获取当前用户的发布资格状态。user_id 为空时返回默认等级的配额"""
    from datetime import datetime

    level = None
    quota = None
    is_guest = False

    if user_id:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return {"ok": False, "reason": "用户不存在"}
        if user.is_muted:
            return {"ok": False, "reason": "你已被禁言，无法发布内容"}
        from services.user_quota import get_or_create_quota
        quota, level = get_or_create_quota(db, user)
        db.commit()
    else:
        is_guest = True
        level = db.query(UserLevel).filter(UserLevel.id == 1).first()

    if not level:
        return {"ok": False, "reason": "用户等级异常"}

    recipe_remaining = quota.recipe_remaining if quota else max(0, level.max_recipes or 0)
    work_remaining = quota.work_remaining if quota else max(0, level.max_works or 0)

    return {
        "ok": True,
        "can_publish_recipe": recipe_remaining > 0,
        "can_publish_work": work_remaining > 0,
        "recipe_remaining": recipe_remaining,
        "work_remaining": work_remaining,
        "recipe_limit": level.max_recipes,
        "recipe_count": (level.max_recipes or 0) - recipe_remaining,
        "work_limit": level.max_works,
        "work_count": (level.max_works or 0) - work_remaining,
        "is_guest": is_guest,
    }


# ========= 配方查看权限 =========


@router.get("/view-status", dependencies=[Depends(current_user)])
def get_view_status(
    user_id: int = Query(...),
    recipe_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
):
    """检查用户今日配方查看状态"""
    from datetime import datetime, time
    from models import RecipeView, UserLevel

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return {"can_view": False, "reason": "用户不存在"}

    from services.user_quota import get_or_create_quota
    quota, level = get_or_create_quota(db, user)

    if recipe_id is not None:
        recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
        if recipe and recipe.user_id == user_id:
            return {"can_view": True, "is_owner": True, "quota_consumed": False, "reason": ""}

        if max(0, level.max_views or 0) == 0:
            db.commit()
            return {
                "can_view": False,
                "remaining": 0,
                "max_views": 0,
                "reason": "当前等级无查看配方权限",
            }

        # Reopening the same recipe on the same day never consumes another
        # quota, so it must remain accessible even when remaining reaches 0.
        from models import UserDailyRecipeView
        from services.user_quota import business_today
        already_viewed = db.query(UserDailyRecipeView.id).filter(
            UserDailyRecipeView.user_id == user_id,
            UserDailyRecipeView.recipe_id == recipe_id,
            UserDailyRecipeView.view_date == business_today(),
        ).first()
        if already_viewed:
            return {"can_view": True, "already_viewed": True, "quota_consumed": False, "reason": ""}

    db.commit()
    max_views = max(0, level.max_views or 0)
    remaining = quota.recipe_view_remaining
    today_views = max_views - remaining
    can_view = remaining > 0
    return {
        "can_view": can_view,
        "today_views": today_views,
        "max_views": max_views,
        "remaining": max(0, remaining),
        "reason": f"今日查看配方已达上限，明天再来看吧" if not can_view else "",
    }


# ========= 待烧（ToBeFired） =========


@router.get("/to-be-fired", dependencies=[Depends(current_user)])
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


@router.post("/to-be-fired", dependencies=[Depends(current_user)])
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


@router.delete("/to-be-fired/{item_id}", dependencies=[Depends(current_user)])
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


@router.put("/to-be-fired/{item_id}", dependencies=[Depends(current_user)])
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
