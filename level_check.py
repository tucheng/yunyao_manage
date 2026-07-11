from sqlalchemy.orm import Session
from fastapi import HTTPException
from models import User, UserLevel, Recipe, Work
from sqlalchemy import func
from datetime import datetime

TRIAL_LEVEL_ID = 5  # 试用者


def downgrade_expired_users(db: Session) -> int:
    """检查所有过期用户，降级为试用者，返回降级人数"""
    expired = db.query(User).filter(
        User.expires_at.isnot(None),
        User.expires_at < datetime.now(),
        User.level_id != TRIAL_LEVEL_ID,
    ).all()
    for u in expired:
        u.level_id = TRIAL_LEVEL_ID
    db.commit()
    return len(expired)


def check_publish_limits(db: Session, user_id: int, recipe_price: int = 0, is_work: bool = False):
    """检查用户发布权限和数量限制"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 禁言检查
    if user.is_muted:
        raise HTTPException(status_code=403, detail="你已被禁言，无法发布内容")

    # 获取用户等级
    level = db.query(UserLevel).filter(UserLevel.id == (user.level_id or 1)).first()
    if not level:
        raise HTTPException(status_code=400, detail="用户等级配置异常")

    if is_work:
        # 作品数限制
        work_count = db.query(Work).filter(Work.user_id == user_id).count()
        if work_count >= level.max_works:
            raise HTTPException(
                status_code=403,
                detail=f"作品数已达上限（{level.max_works}个），当前等级无法继续发布",
            )
        return

    # ===== 配方限制 =====
    is_paid = recipe_price > 0

    if is_paid:
        # 付费配方权限
        if not level.can_publish_paid:
            raise HTTPException(
                status_code=403,
                detail=f"当前等级「{level.name}」无法发布付费配方",
            )
        paid_count = db.query(Recipe).filter(
            Recipe.user_id == user_id, Recipe.price > 0
        ).count()
        if paid_count >= level.max_paid_recipes:
            raise HTTPException(
                status_code=403,
                detail=f"付费配方已达上限（{level.max_paid_recipes}个），请升级等级",
            )
    else:
        # 免费配方上限
        free_count = db.query(Recipe).filter(
            Recipe.user_id == user_id,
            Recipe.price == 0,
        ).count()
        if free_count >= level.max_free_recipes:
            raise HTTPException(
                status_code=403,
                detail=f"免费配方已达上限（{level.max_free_recipes}个），当前等级无法继续发布",
            )


def check_paid_switch(db: Session, user_id: int, recipe_id: int):
    """检查把配方从免费改为付费时是否允许"""
    level = db.query(UserLevel).filter(
        UserLevel.id == (db.query(User.level_id).filter(User.id == user_id).scalar() or 1)
    ).first()
    if not level or not level.can_publish_paid:
        raise HTTPException(
            status_code=403,
            detail=f"当前等级「{level.name}」无法发布付费配方",
        )
    # 检查付费数量（排除自身）
    paid_count = db.query(Recipe).filter(
        Recipe.user_id == user_id,
        Recipe.price > 0,
        Recipe.id != recipe_id,
    ).count()
    if paid_count >= level.max_paid_recipes:
        raise HTTPException(
            status_code=403,
            detail=f"付费配方已达上限（{level.max_paid_recipes}个）",
        )
