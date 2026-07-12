import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import get_db
from models import AppSetting, User, UserLevel, Recipe, Work, Notification, WorkAttributeOption, Material
from pydantic import BaseModel
from typing import Optional
from app_config import ADMIN_TOKEN, ADMIN_USER_IDS
from auth_utils import decode_access_token, hash_password, verify_password
from encryption_utils import decrypt
from verification_sender import get_settings as get_verification_settings, save_settings as save_verification_settings
from color_names import get_color_range_config
from routes.works import TEMPERATURE_RANGE_CONFIG
from services.user_quota import SYSTEM_LEVEL_NAMES, reset_user_quota

router = APIRouter(prefix="/admin", tags=["后台管理"])

# ===== 管理认证（支持 ADMIN_TOKEN 或用户登录 JWT）=====

class AdminLoginRequest(BaseModel):
    username: str
    password: str


def verify_admin(token: str = Query(...)):
    # 方式1: ADMIN_TOKEN 兼容
    if ADMIN_TOKEN and token == ADMIN_TOKEN:
        return
    # 方式2: 用户 JWT + DB is_admin 字段
    try:
        payload = decode_access_token(token)
        uid = int(payload.get("sub", 0))
        if uid in ADMIN_USER_IDS:
            return
        from database import SessionLocal
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == uid).first()
            if user and user.is_admin:
                return
        finally:
            db.close()
    except Exception:
        pass
    raise HTTPException(status_code=403, detail="无权访问")


@router.post("/login")
def admin_login(body: AdminLoginRequest, db: Session = Depends(get_db)):
    uname = body.username.strip()
    user = db.query(User).filter(User.username == uname).first()
    if not user:
        user = User.by_email_or_phone(db, uname)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    ok, _ = verify_password(body.password, user.password if user else "")
    if not ok:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if user.id not in ADMIN_USER_IDS and not user.is_admin:
        raise HTTPException(status_code=403, detail="该账号无管理权限")
    from auth_utils import create_access_token, user_role
    token = create_access_token(user)
    return {
        "token": token,
        "user_id": user.id,
        "nickname": user.nickname,
        "role": user_role(user),
    }


# ========= 用户管理 =========

@router.get("/users")
def list_users(q: str = "", page: int = 1, page_size: int = Query(default=20, alias="page_size"),
               token: str = Query(...), db: Session = Depends(get_db)):
    verify_admin(token)
    qry = db.query(User)
    if q:
        qry = qry.filter(
            User.nickname.like(f"%{q}%")
            | User.username.like(f"%{q}%")
        )

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
            "username": u.username or "",
            "nickname": u.nickname,
            "openid": u.openid[:8] + "..." if u.openid else "",
            "balance": u.balance or 0,
            "trust_score": u.trust_score or 100,
            "level_id": u.level_id or 1,
            "level_name": level["name"],
            "is_muted": bool(u.is_muted),
            "is_admin": bool(u.is_admin),
            "expires_at": str(u.expires_at) if u.expires_at else "",
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
        "is_admin": bool(u.is_admin),
        "expires_at": str(u.expires_at) if u.expires_at else "",
        "recipe_count": recipe_count,
        "paid_count": paid_count,
        "free_count": recipe_count - paid_count,
        "work_count": work_count,
        "created_at": str(u.created_at) if u.created_at else "",
    }


class UpdateUserBody(BaseModel):
    level_id: Optional[int] = None
    is_muted: Optional[bool] = None
    is_admin: Optional[bool] = None
    expires_at: Optional[str] = None  # ISO 格式日期时间，空字符串重置为今天


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
        reset_user_quota(db, u)

    if body.is_muted is not None:
        u.is_muted = body.is_muted

    if body.is_admin is not None:
        u.is_admin = body.is_admin

    if body.expires_at is not None:
        from datetime import datetime
        try:
            u.expires_at = datetime.fromisoformat(body.expires_at) if body.expires_at else datetime.now()
        except ValueError:
            raise HTTPException(status_code=400, detail="expires_at 格式无效，请使用 ISO 格式如 2026-12-31T23:59:59")

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
            "max_paid_recipes": l.max_paid_recipes,
            "max_free_recipes": l.max_free_recipes,
            "max_works": l.max_works,
            "max_views": l.max_views,
            "description": l.description,
            "sort_order": l.sort_order,
            "user_count": db.query(User).filter(User.level_id == l.id).count(),
        }
        for l in levels
    ]


class LevelBody(BaseModel):
    name: str
    max_paid_recipes: int = 0
    max_free_recipes: int = 10
    max_works: int = 50
    max_views: int = 0
    description: str = ""
    sort_order: int = 0

    def validate_quotas(self):
        values = (self.max_paid_recipes, self.max_free_recipes, self.max_works, self.max_views)
        if any(value < 0 for value in values):
            raise HTTPException(status_code=400, detail="每日额度不能小于0")


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
    body.validate_quotas()
    level = UserLevel(**body.model_dump())
    db.add(level)
    db.commit()
    db.refresh(level)
    return {"id": level.id, "ok": True}


@router.put("/levels/{level_id}")
def update_level(level_id: int, body: LevelBody, token: str = Query(...), db: Session = Depends(get_db)):
    verify_admin(token)
    body.validate_quotas()
    l = db.query(UserLevel).filter(UserLevel.id == level_id).first()
    if not l:
        raise HTTPException(status_code=404, detail="等级不存在")
    values = body.model_dump()
    if level_id in SYSTEM_LEVEL_NAMES:
        values["name"] = SYSTEM_LEVEL_NAMES[level_id]
    for k, v in values.items():
        setattr(l, k, v)
    db.commit()
    return {"ok": True}


@router.delete("/levels/{level_id}")
def delete_level(level_id: int, token: str = Query(...), db: Session = Depends(get_db)):
    verify_admin(token)
    if level_id in SYSTEM_LEVEL_NAMES:
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


# ========= 作品属性选项配置 =========

class WorkAttributeOptionBody(BaseModel):
    category: str
    value: str
    sort_order: int = 0


@router.get("/work-attributes")
def list_work_attributes(token: str = Query(...), db: Session = Depends(get_db)):
    """获取所有作品属性选项，按 category 分组"""
    verify_admin(token)
    options = db.query(WorkAttributeOption).order_by(WorkAttributeOption.category, WorkAttributeOption.sort_order).all()
    grouped = {}
    for opt in options:
        grouped.setdefault(opt.category, []).append({
            "id": opt.id,
            "value": opt.value,
            "sort_order": opt.sort_order,
        })
    return grouped


@router.post("/work-attributes")
def create_work_attribute(body: WorkAttributeOptionBody, token: str = Query(...), db: Session = Depends(get_db)):
    verify_admin(token)
    opt = WorkAttributeOption(category=body.category, value=body.value, sort_order=body.sort_order)
    db.add(opt)
    db.commit()
    db.refresh(opt)
    return {"id": opt.id, "ok": True}


@router.put("/work-attributes/{opt_id}")
def update_work_attribute(opt_id: int, body: WorkAttributeOptionBody, token: str = Query(...), db: Session = Depends(get_db)):
    verify_admin(token)
    opt = db.query(WorkAttributeOption).filter(WorkAttributeOption.id == opt_id).first()
    if not opt:
        raise HTTPException(status_code=404, detail="选项不存在")
    opt.category = body.category
    opt.value = body.value
    opt.sort_order = body.sort_order
    db.commit()
    return {"ok": True}


@router.delete("/work-attributes/{opt_id}")
def delete_work_attribute(opt_id: int, token: str = Query(...), db: Session = Depends(get_db)):
    verify_admin(token)
    opt = db.query(WorkAttributeOption).filter(WorkAttributeOption.id == opt_id).first()
    if not opt:
        raise HTTPException(status_code=404, detail="选项不存在")
    db.delete(opt)
    db.commit()
    return {"ok": True}


# ========= 公开接口（不含管理验证）=========

@router.get("/public/work-attributes")
def get_public_work_attributes(db: Session = Depends(get_db)):
    """公开查询，前端发布/搜索作品时用"""
    options = db.query(WorkAttributeOption).order_by(WorkAttributeOption.category, WorkAttributeOption.sort_order).all()
    grouped = {}
    for opt in options:
        grouped.setdefault(opt.category, []).append(opt.value)
    return grouped


# ========= Glazy 海外材料查询 =========

@router.get("/glazy-materials")
def list_glazy_materials(
    q: str = "",
    page: int = 1,
    page_size: int = Query(default=50, alias="page_size"),
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    """查询 Glazy 海外材料"""
    verify_admin(token)
    qry = db.query(Material).filter(Material.source == "glazy")
    if q:
        like = f"%{q}%"
        qry = qry.filter(
            Material.name.like(like)
            | Material.name_en.like(like)
        )
    total = qry.count()
    items = qry.order_by(Material.name).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "results": [
            {
                "glazy_id": m.source_id,
                "name": m.name_en,
                "name_cn": m.name or "",
                "is_primitive": bool(m.is_primitive),
                "sio2": m.sio2, "al2o3": m.al2o3,
                "na2o": m.na2o, "k2o": m.k2o, "mgo": m.mgo,
                "cao": m.cao, "fe2o3": m.fe2o3, "tio2": m.tio2,
                "zno": m.zno, "b2o3": m.b2o3, "p2o5": m.p2o5, "loi": m.loi,
                "thermal_expansion": m.thermal_expansion,
            }
            for m in items
        ],
        "total": total,
        "page": page,
    }


@router.get("/glazy-materials/{glazy_id}")
def get_glazy_material(glazy_id: int, token: str = Query(...), db: Session = Depends(get_db)):
    """查询单个材料详情"""
    verify_admin(token)
    m = db.query(Material).filter(
        Material.source == "glazy",
        Material.source_id == glazy_id,
    ).first()
    if not m:
        raise HTTPException(status_code=404, detail="材料不存在")
    return {
        "glazy_id": m.source_id,
        "name": m.name_en,
        "name_cn": m.name or "",
        "is_primitive": bool(m.is_primitive),
        "sio2": m.sio2, "al2o3": m.al2o3,
        "na2o": m.na2o, "k2o": m.k2o, "mgo": m.mgo,
        "cao": m.cao, "fe2o3": m.fe2o3, "tio2": m.tio2,
        "zno": m.zno, "b2o3": m.b2o3, "p2o5": m.p2o5, "loi": m.loi,
        "thermal_expansion": m.thermal_expansion,
    }


@router.get("/materials")
def admin_list_materials(
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=200),
    db: Session = Depends(get_db),
    _=Depends(verify_admin),
):
    """管理员查看原材料列表"""
    q = db.query(Material)
    if search:
        q = q.filter(
            Material.name.like(f"%{search}%") |
            Material.name_en.like(f"%{search}%")
        )
    total = q.count()
    items = q.order_by(Material.source, Material.name).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "data": [
            {
                "id": m.id,
                "name": m.name,
                "name_en": m.name_en,
                "source": m.source,
                "source_id": m.source_id,
                "formula": m.formula or "",
                "molecular_weight": m.molecular_weight or "",
                "category": m.category or "",
                "sio2": m.sio2, "al2o3": m.al2o3,
                "fe2o3": m.fe2o3, "tio2": m.tio2,
                "cao": m.cao, "mgo": m.mgo,
                "na2o": m.na2o, "k2o": m.k2o,
                "zno": m.zno, "b2o3": m.b2o3,
                "p2o5": m.p2o5, "li2o": m.li2o,
                "mno2": m.mno2, "coo": m.coo,
                "sno2": m.sno2, "cuo": m.cuo,
                "cr2o3": m.cr2o3, "pbo": m.pbo,
                "bao": m.bao, "sro": m.sro,
                "loi": m.loi, "thermal_expansion": m.thermal_expansion,
            }
            for m in items
        ],
    }
