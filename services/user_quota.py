from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import RedeemLog, User, UserDailyRecipeView, UserLevel, UserUsageQuota
from services.business_errors import QuotaExceeded


TRIAL_LEVEL_ID = 1
NORMAL_LEVEL_ID = 2
MEMBER_LEVEL_ID = 3
SYSTEM_LEVEL_NAMES = {
    TRIAL_LEVEL_ID: "会员试用者",
    NORMAL_LEVEL_ID: "普通用户",
    MEMBER_LEVEL_ID: "会员用户",
}

QuotaKind = Literal["recipe", "work", "recipe_view"]
BUSINESS_TIMEZONE = ZoneInfo("Asia/Shanghai")


def business_today() -> date:
    """Return the quota date in the product's business timezone."""
    return datetime.now(BUSINESS_TIMEZONE).date()

_REMAINING_FIELD = {
    "recipe": "recipe_remaining",
    "work": "work_remaining",
    "recipe_view": "recipe_view_remaining",
}
_LIMIT_FIELD = {
    "recipe": "max_recipes",
    "work": "max_works",
    "recipe_view": "max_views",
}
_QUOTA_LABEL = {
    "recipe": "发布配方",
    "work": "发布作品",
    "recipe_view": "查看配方",
}


def ensure_system_levels(db: Session) -> None:
    """只保证三个业务固定等级存在并保持固定名称，不处理其他测试等级。"""
    for level_id, name in SYSTEM_LEVEL_NAMES.items():
        level = db.query(UserLevel).filter(UserLevel.id == level_id).first()
        if level is None:
            db.add(UserLevel(id=level_id, name=name, sort_order=level_id))
        elif level.name != name:
            level.name = name
    db.flush()


def downgrade_user_if_expired(user: User, now: datetime | None = None) -> bool:
    """普通用户永久有效；其他等级到期后降为普通用户但保留会员到期日。"""
    now = now or datetime.now()
    if user.level_id in (TRIAL_LEVEL_ID, MEMBER_LEVEL_ID) and user.expires_at and user.expires_at <= now:
        user.level_id = NORMAL_LEVEL_ID
        return True
    return False


def _level_for_user(db: Session, user: User) -> UserLevel:
    downgrade_user_if_expired(user)
    level = db.query(UserLevel).filter(UserLevel.id == (user.level_id or TRIAL_LEVEL_ID)).first()
    if not level:
        raise HTTPException(status_code=400, detail="用户等级配置异常")
    return level


def _reset_quota(quota: UserUsageQuota, level: UserLevel, quota_date: date) -> None:
    quota.quota_date = quota_date
    quota.recipe_remaining = max(0, level.max_recipes or 0)
    quota.work_remaining = max(0, level.max_works or 0)
    quota.recipe_view_remaining = max(0, level.max_views or 0)


def get_or_create_quota(
    db: Session,
    user: User,
    *,
    for_update: bool = False,
    force_reset: bool = False,
) -> tuple[UserUsageQuota, UserLevel]:
    today = business_today()
    previous_level_id = user.level_id
    level = _level_for_user(db, user)
    force_reset = force_reset or user.level_id != previous_level_id
    query = db.query(UserUsageQuota).filter(UserUsageQuota.user_id == user.id)
    if for_update:
        query = query.with_for_update()
    quota = query.first()
    if quota is None:
        quota = UserUsageQuota(user_id=user.id, quota_date=today)
        _reset_quota(quota, level, today)
        db.add(quota)
        db.flush()
    elif force_reset or quota.quota_date != today:
        _reset_quota(quota, level, today)
        db.flush()
    return quota, level


def reset_user_quota(db: Session, user: User) -> UserUsageQuota:
    quota, _ = get_or_create_quota(db, user, for_update=True, force_reset=True)
    return quota


def sync_level_quotas(
    db: Session,
    level_id: int,
    previous_limits: dict[str, int],
    new_limits: dict[str, int],
) -> int:
    """等级额度修改后立即同步当日余额，同时保留用户今天已经消耗的次数。"""
    today = business_today()
    quotas = (
        db.query(UserUsageQuota)
        .join(User, User.id == UserUsageQuota.user_id)
        .filter(User.level_id == level_id)
        .all()
    )
    fields = {
        "recipe_remaining": "max_recipes",
        "work_remaining": "max_works",
        "recipe_view_remaining": "max_views",
    }
    for quota in quotas:
        if quota.quota_date != today:
            quota.quota_date = today
            for remaining_field, limit_field in fields.items():
                setattr(quota, remaining_field, max(0, new_limits[limit_field]))
            continue
        for remaining_field, limit_field in fields.items():
            old_limit = max(0, previous_limits[limit_field])
            new_limit = max(0, new_limits[limit_field])
            consumed = max(0, old_limit - max(0, getattr(quota, remaining_field) or 0))
            setattr(quota, remaining_field, max(0, new_limit - consumed))
    db.flush()
    return len(quotas)


def consume_quota(db: Session, user: User, kind: QuotaKind) -> int:
    if kind in ("recipe", "work") and user.is_muted:
        raise HTTPException(status_code=403, detail="你已被禁言，无法发布内容")
    quota, _ = get_or_create_quota(db, user, for_update=True)
    field = _REMAINING_FIELD[kind]
    remaining = getattr(quota, field) or 0
    if remaining <= 0:
        if kind == "recipe":
            raise QuotaExceeded("recipe", "今天发布配方的额度已用完！")
        else:
            raise QuotaExceeded(kind, f"今天{_QUOTA_LABEL[kind]}额度已使用完")
    remaining -= 1
    setattr(quota, field, remaining)
    db.flush()
    return remaining


def consume_recipe_view_once(db: Session, user: User, recipe_id: int) -> tuple[bool, int]:
    today = business_today()
    quota, level = get_or_create_quota(db, user, for_update=True)
    # max_views=0 是硬性禁止查看，不能被“今天曾看过该配方”绕过。
    if max(0, level.max_views or 0) == 0:
        raise QuotaExceeded("recipe_view", "当前等级无查看配方权限")
    viewed = db.query(UserDailyRecipeView).filter(
        UserDailyRecipeView.user_id == user.id,
        UserDailyRecipeView.recipe_id == recipe_id,
        UserDailyRecipeView.view_date == today,
    ).with_for_update().first()
    if viewed:
        return False, quota.recipe_view_remaining
    remaining = quota.recipe_view_remaining or 0
    if remaining <= 0:
        raise QuotaExceeded("recipe_view", "今天查看配方额度已使用完")
    remaining -= 1
    quota.recipe_view_remaining = remaining
    db.add(UserDailyRecipeView(user_id=user.id, recipe_id=recipe_id, view_date=today))
    db.flush()
    return True, remaining


def quota_status(db: Session, user: User) -> dict:
    quota, level = get_or_create_quota(db, user)
    return {
        "quota_date": str(quota.quota_date),
        "recipe_remaining": quota.recipe_remaining,
        "work_remaining": quota.work_remaining,
        "recipe_view_remaining": quota.recipe_view_remaining,
        "redeem_count": quota.redeem_count,
        "max_recipes": level.max_recipes,
        "max_works": level.max_works,
        "max_views": level.max_views,
    }


def run_daily_maintenance(db: Session) -> tuple[int, int]:
    """幂等日切：降级到期用户，并把过期日期的额度刷新到今天。"""
    now = datetime.now()
    downgraded = 0
    refreshed = 0
    ensure_system_levels(db)
    users = db.query(User).all()
    levels = {level.id: level for level in db.query(UserLevel).all()}
    quotas = {quota.user_id: quota for quota in db.query(UserUsageQuota).all()}
    redeemed_user_ids = {
        user_id for (user_id,) in db.query(RedeemLog.user_id).distinct().all()
    }
    for user in users:
        upgraded_from_redeem = False
        if (
            user.level_id == TRIAL_LEVEL_ID
            and user.expires_at
            and user.expires_at > now
            and user.id in redeemed_user_ids
        ):
            user.level_id = MEMBER_LEVEL_ID
            upgraded_from_redeem = True
        if downgrade_user_if_expired(user, now):
            downgraded += 1
        quota = quotas.get(user.id)
        if upgraded_from_redeem or quota is None or quota.quota_date != business_today():
            level = levels.get(user.level_id or TRIAL_LEVEL_ID)
            if level is None:
                raise RuntimeError(f"Missing user level {user.level_id}")
            if quota is None:
                quota = UserUsageQuota(user_id=user.id, quota_date=business_today())
                db.add(quota)
                quotas[user.id] = quota
            _reset_quota(quota, level, business_today())
            refreshed += 1
    db.commit()
    return downgraded, refreshed
