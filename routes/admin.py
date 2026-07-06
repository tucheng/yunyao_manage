import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import get_db
from models import AppSetting, User, UserLevel, Recipe, Work, Notification
from pydantic import BaseModel
from typing import Optional
from app_config import ADMIN_TOKEN
from verification_sender import get_settings as get_verification_settings, save_settings as save_verification_settings
from color_names import get_color_range_config
from routes.works import TEMPERATURE_RANGE_CONFIG

router = APIRouter(prefix="/admin", tags=["后台管理"])

# ===== 简易管理认证 =====

def verify_admin(token: str = Query(...)):
    if not ADMIN_TOKEN or token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="无权访问")


# ========= 用户管理 =========

@router.get("/users")
def list_users(q: str = "", page: int = 1, page_size: int = Query(default=20, alias="page_size"),
               token: str = Query(...), db: Session = Depends(get_db)):
    verify_admin(token)
    qry = db.query(User)
    if q:
        qry = qry.filter(User.nickname.like(f"%{q}%"))

    total = qry.count()
    users = qry.order_by(User.id.desc()).offset((page - 1) * page_size).limit(page_size).all()

    # 统计发布数量
    user_ids = [u.id for u in users]
    recipe_counts = dict(
        db.query(Recipe.user_id, func.count(Recipe.id)).filter(Recipe.user_id.in_(user_ids)).group_by(Recipe.user_id).all()
    )
    paid_counts = dict(
        db.query(Recipe.user_id, func.count(Recipe.id)).filter(
            Recipe.user_id.in_(user_ids), Recipe.price > 0
        ).group_by(Recipe.user_id).all()
    )
    work_counts = dict(
        db.query(Work.user_id, func.count(Work.id)).filter(Work.user_id.in_(user_ids)).group_by(Work.user_id).all()
    )

    # 等级信息
    levels = {l.id: {"id": l.id, "name": l.name} for l in db.query(UserLevel).all()}

    result = []
    for u in users:
        level = levels.get(u.level_id or 1, {"id": 1, "name": "普通用户"})
        result.append({
            "id": u.id,
            "nickname": u.nickname,
            "openid": u.openid[:8] + "..." if u.openid else "",
            "balance": u.balance or 0,
            "trust_score": u.trust_score or 100,
            "level_id": u.level_id or 1,
            "level_name": level["name"],
            "is_muted": bool(u.is_muted),
            "recipe_count": recipe_counts.get(u.id, 0),
            "paid_count": paid_counts.get(u.id, 0),
            "work_count": work_counts.get(u.id, 0),
            "created_at": str(u.created_at) if u.created_at else "",
        })

    return {"results": result, "total": total, "page": page, "page_size": page_size}


@router.get("/users/{user_id}")
def get_user(user_id: int, token: str = Query(...), db: Session = Depends(get_db)):
    verify_admin(token)
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")

    recipe_count = db.query(Recipe).filter(Recipe.user_id == user_id).count()
    paid_count = db.query(Recipe).filter(Recipe.user_id == user_id, Recipe.price > 0).count()
    work_count = db.query(Work).filter(Work.user_id == user_id).count()
    levels = {l.id: l.name for l in db.query(UserLevel).all()}

    return {
        "id": u.id,
        "nickname": u.nickname,
        "openid": u.openid,
        "avatar": u.avatar,
        "balance": u.balance or 0,
        "trust_score": u.trust_score or 100,
        "level_id": u.level_id or 1,
        "level_name": levels.get(u.level_id or 1, "普通用户"),
        "is_muted": bool(u.is_muted),
        "recipe_count": recipe_count,
        "paid_count": paid_count,
        "free_count": recipe_count - paid_count,
        "work_count": work_count,
        "created_at": str(u.created_at) if u.created_at else "",
    }


class UpdateUserBody(BaseModel):
    level_id: Optional[int] = None
    is_muted: Optional[bool] = None


@router.put("/users/{user_id}")
def update_user(user_id: int, body: UpdateUserBody, token: str = Query(...), db: Session = Depends(get_db)):
    verify_admin(token)
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")

    if body.level_id is not None:
        level = db.query(UserLevel).filter(UserLevel.id == body.level_id).first()
        if not level:
            raise HTTPException(status_code=400, detail="等级不存在")
        u.level_id = body.level_id

    if body.is_muted is not None:
        u.is_muted = body.is_muted

    db.commit()
    return {"ok": True}


# ========= 等级管理 =========

@router.get("/levels")
def list_levels(token: str = Query(...), db: Session = Depends(get_db)):
    verify_admin(token)
    levels = db.query(UserLevel).order_by(UserLevel.sort_order).all()
    return [
        {
            "id": l.id,
            "name": l.name,
            "can_publish_paid": bool(l.can_publish_paid),
            "max_paid_recipes": l.max_paid_recipes,
            "max_free_recipes": l.max_free_recipes,
            "max_works": l.max_works,
            "description": l.description,
            "sort_order": l.sort_order,
            "user_count": db.query(User).filter(User.level_id == l.id).count(),
        }
        for l in levels
    ]


class LevelBody(BaseModel):
    name: str
    can_publish_paid: bool = False
    max_paid_recipes: int = 0
    max_free_recipes: int = 10
    max_works: int = 50
    description: str = ""
    sort_order: int = 0


class VerificationSettingsBody(BaseModel):
    verification_account_mode: str = "either"
    verification_channel: str = "debug"
    smtp_host: str = ""
    smtp_port: str = "465"
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_ssl: str = "1"
    email_subject: str = "云窑验证码"
    email_body_template: str = "您的验证码是 {{code}}，10分钟内有效。"
    sms_api_url: str = ""
    sms_method: str = "POST"
    sms_headers_json: str = "{}"
    sms_body_template: str = "{\"phone\":\"{{phone}}\",\"code\":\"{{code}}\"}"


class TemperatureRangeBody(BaseModel):
    value: str
    label: str
    min: float = 0
    max: float = 0
    description: str = ""


class ColorRangeBody(BaseModel):
    value: str
    label: str
    names: list[str] = []
    description: str = ""


class WorkSearchSettingsBody(BaseModel):
    temperature_ranges: list[TemperatureRangeBody] = []
    color_ranges: list[ColorRangeBody] = []


def _get_json_setting(db: Session, key: str, default):
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if not row or not row.value:
        return default
    try:
        value = json.loads(row.value)
    except Exception:
        return default
    return value if isinstance(value, type(default)) else default


def _set_json_setting(db: Session, key: str, value) -> None:
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if not row:
        row = AppSetting(key=key)
        db.add(row)
    row.value = json.dumps(value, ensure_ascii=False)


def _ensure_json_setting(db: Session, key: str, default):
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if not row or not row.value:
        _set_json_setting(db, key, default)
        db.commit()
        return default
    return _get_json_setting(db, key, default)


@router.post("/levels")
def create_level(body: LevelBody, token: str = Query(...), db: Session = Depends(get_db)):
    verify_admin(token)
    level = UserLevel(**body.model_dump())
    db.add(level)
    db.commit()
    db.refresh(level)
    return {"id": level.id, "ok": True}


@router.put("/levels/{level_id}")
def update_level(level_id: int, body: LevelBody, token: str = Query(...), db: Session = Depends(get_db)):
    verify_admin(token)
    l = db.query(UserLevel).filter(UserLevel.id == level_id).first()
    if not l:
        raise HTTPException(status_code=404, detail="等级不存在")
    for k, v in body.model_dump().items():
        setattr(l, k, v)
    db.commit()
    return {"ok": True}


@router.delete("/levels/{level_id}")
def delete_level(level_id: int, token: str = Query(...), db: Session = Depends(get_db)):
    verify_admin(token)
    if level_id <= 4:
        raise HTTPException(status_code=400, detail="默认等级不可删除")
    count = db.query(User).filter(User.level_id == level_id).count()
    if count > 0:
        raise HTTPException(status_code=400, detail=f"有{count}个用户属于此等级，请先转移")
    db.query(UserLevel).filter(UserLevel.id == level_id).delete()
    db.commit()
    return {"ok": True}


# ========= 统计数据 =========

@router.get("/stats")
def stats(token: str = Query(...), db: Session = Depends(get_db)):
    verify_admin(token)
    return {
        "user_count": db.query(User).count(),
        "recipe_count": db.query(Recipe).count(),
        "paid_recipe_count": db.query(Recipe).filter(Recipe.price > 0).count(),
        "work_count": db.query(Work).count(),
        "muted_count": db.query(User).filter(User.is_muted == True).count(),
    }


@router.get("/verification-settings")
def get_verification_config(token: str = Query(...), db: Session = Depends(get_db)):
    verify_admin(token)
    return get_verification_settings(db, mask_sensitive=True)


@router.put("/verification-settings")
def update_verification_config(
    body: VerificationSettingsBody,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    verify_admin(token)
    if body.verification_account_mode not in ("sms", "email", "either"):
        raise HTTPException(status_code=400, detail="注册/登录验证方式不正确")
    if body.verification_channel not in ("debug", "email", "sms"):
        raise HTTPException(status_code=400, detail="验证码渠道不正确")
    return save_verification_settings(db, body.model_dump())


# ========= 作品搜索配置 =========

@router.get("/work-search-settings")
def get_work_search_settings(token: str = Query(...), db: Session = Depends(get_db)):
    verify_admin(token)
    return {
        "temperature_ranges": _ensure_json_setting(db, "work_search_temperature_ranges", TEMPERATURE_RANGE_CONFIG),
        "color_ranges": _ensure_json_setting(db, "work_search_color_ranges", get_color_range_config()),
    }
# ========= 付费功能开关 =========

SYSTEM_PAID_ENABLED_KEY = "paid_enabled"


@router.get("/paid-enabled")
def get_paid_enabled(token: str = Query(...), db: Session = Depends(get_db)):
    verify_admin(token)
    return {"paid_enabled": _get_json_setting(db, SYSTEM_PAID_ENABLED_KEY, False)}


class PaidEnabledBody(BaseModel):
    paid_enabled: bool


@router.put("/paid-enabled")
def update_paid_enabled(
    body: PaidEnabledBody,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    verify_admin(token)
    _set_json_setting(db, SYSTEM_PAID_ENABLED_KEY, body.paid_enabled)
    db.commit()
    return {"ok": True, "paid_enabled": body.paid_enabled}


@router.put("/work-search-settings")
def update_work_search_settings(
    body: WorkSearchSettingsBody,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    verify_admin(token)
    temperature_ranges = [item.model_dump() for item in body.temperature_ranges]
    color_ranges = [item.model_dump() for item in body.color_ranges]

    if not temperature_ranges:
        raise HTTPException(status_code=400, detail="至少配置一个温度范围")
    if not color_ranges:
        raise HTTPException(status_code=400, detail="至少配置一个颜色范围")

    seen_temp = set()
    for item in temperature_ranges:
        if not item["value"] or not item["label"]:
            raise HTTPException(status_code=400, detail="温度范围的编码和名称不能为空")
        if item["value"] in seen_temp:
            raise HTTPException(status_code=400, detail=f"温度范围编码重复：{item['value']}")
        if item["min"] > item["max"]:
            raise HTTPException(status_code=400, detail=f"{item['label']} 的最低温不能大于最高温")
        seen_temp.add(item["value"])

    seen_color = set()
    for item in color_ranges:
        item["names"] = [name.strip() for name in item.get("names", []) if name and name.strip()]
        if not item["value"] or not item["label"]:
            raise HTTPException(status_code=400, detail="颜色范围的编码和名称不能为空")
        if item["value"] in seen_color:
            raise HTTPException(status_code=400, detail=f"颜色范围编码重复：{item['value']}")
        if not item["names"]:
            raise HTTPException(status_code=400, detail=f"{item['label']} 至少要包含一个颜色名")
        seen_color.add(item["value"])

    _set_json_setting(db, "work_search_temperature_ranges", temperature_ranges)
    _set_json_setting(db, "work_search_color_ranges", color_ranges)
    db.commit()
    return {"ok": True}
