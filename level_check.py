from sqlalchemy.orm import Session
from fastapi import HTTPException
from models import User, UserLevel, Recipe
from sqlalchemy import func
from datetime import datetime

from services.user_quota import NORMAL_LEVEL_ID, consume_quota, run_daily_maintenance


def downgrade_expired_users(db: Session) -> int:
    """兼容旧调用：到期用户降为普通用户并执行当天额度维护。"""
    downgraded, _ = run_daily_maintenance(db)
    return downgraded


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
        consume_quota(db, user, "work")
        return

    # ===== 配方限制 =====
    is_paid = recipe_price > 0

    if is_paid:
        # 付费配方权限：max_paid_recipes > 0 表示可发付费
        if level.max_paid_recipes <= 0:
            raise HTTPException(
                status_code=403,
                detail=f"当前等级「{level.name}」无法发布付费配方",
            )
        consume_quota(db, user, "paid_recipe")
    else:
        # 免费配方上限
        consume_quota(db, user, "free_recipe")


def check_paid_switch(db: Session, user_id: int, recipe_id: int):
    """检查把配方从免费改为付费时是否允许"""
    level = db.query(UserLevel).filter(
        UserLevel.id == (db.query(User.level_id).filter(User.id == user_id).scalar() or 1)
    ).first()
    if not level or level.max_paid_recipes <= 0:
        raise HTTPException(
            status_code=403,
            detail=f"当前等级「{level.name}」无法发布付费配方",
        )
    user = db.query(User).filter(User.id == user_id).first()
    consume_quota(db, user, "paid_recipe")
