import json
from datetime import datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import and_, exists, func, or_
from database import get_db
from models import (
    Complaint, ComplaintReply, User, UserLevel, Recipe, RecipeIngredient, Work,
    WorkAttributeOption, Material, MaterialFamily, MaterialMergeLog,
    MaterialRevision, MaterialSubstitution,
)
from pydantic import BaseModel
from typing import Optional
from app_config import ADMIN_USER_IDS
from auth_utils import current_admin, decode_access_token, token_from_request, verify_password
from verification_sender import get_settings as get_verification_settings, save_settings as save_verification_settings
from color_names import get_color_range_config
from services.settings_store import (
    ensure_json_setting as _ensure_json_setting,
    set_json_setting as _set_json_setting,
)
from services.work_search import TEMPERATURE_RANGE_CONFIG
from services.user_quota import SYSTEM_LEVEL_NAMES, reset_user_quota
from routes.complaints import serialize_complaint
from routes.notifications import add_notification
from services.material_analysis import (
    affected_recipe_ids,
    backfill_recipe_material_links,
    composition_fingerprint,
    duplicate_groups,
    merge_materials,
    prepare_material,
    recalculate_material_recipes,
    rollback_material_merge,
)
from services.material_catalog import clean_molecule_data, catalog_payload

router = APIRouter(prefix="/admin", tags=["后台管理"])
verify_admin = current_admin

# ===== 管理认证（仅接受 Authorization Bearer JWT）=====

class AdminLoginRequest(BaseModel):
    username: str
    password: str


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
               _admin=Depends(verify_admin), db: Session = Depends(get_db)):
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
            "trust_score": u.trust_score or 100,
            "level_id": u.level_id or 1,
            "level_name": level["name"],
            "is_muted": bool(u.is_muted),
            "is_admin": bool(u.is_admin),
            "expires_at": str(u.expires_at) if u.expires_at else "",
            "recipe_count": recipe_counts.get(u.id, 0),
            "work_count": work_counts.get(u.id, 0),
            "created_at": str(u.created_at) if u.created_at else "",
        })

    return {"results": result, "total": total, "page": page, "page_size": page_size}


@router.get("/users/{user_id}")
def get_user(user_id: int, _admin=Depends(verify_admin), db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")

    recipe_count = db.query(Recipe).filter(Recipe.user_id == user_id).count()
    work_count = db.query(Work).filter(Work.user_id == user_id).count()
    levels = {l.id: l.name for l in db.query(UserLevel).all()}

    return {
        "id": u.id,
        "nickname": u.nickname,
        "avatar": u.avatar,
        "trust_score": u.trust_score or 100,
        "level_id": u.level_id or 1,
        "level_name": levels.get(u.level_id or 1, "普通用户"),
        "is_muted": bool(u.is_muted),
        "is_admin": bool(u.is_admin),
        "expires_at": str(u.expires_at) if u.expires_at else "",
        "recipe_count": recipe_count,
        "work_count": work_count,
        "created_at": str(u.created_at) if u.created_at else "",
    }


class UpdateUserBody(BaseModel):
    level_id: Optional[int] = None
    is_muted: Optional[bool] = None
    is_admin: Optional[bool] = None
    expires_at: Optional[str] = None  # ISO 格式日期时间，空字符串重置为今天


@router.put("/users/{user_id}")
def update_user(user_id: int, body: UpdateUserBody, _admin=Depends(verify_admin), db: Session = Depends(get_db)):
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
def list_levels(_admin=Depends(verify_admin), db: Session = Depends(get_db)):
    levels = db.query(UserLevel).order_by(UserLevel.sort_order).all()
    return [
        {
            "id": l.id,
            "name": l.name,
            "max_recipes": l.max_recipes,
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
    max_recipes: int = 10
    max_works: int = 50
    max_views: int = 0
    description: str = ""
    sort_order: int = 0

    def validate_quotas(self):
        values = (self.max_recipes, self.max_works, self.max_views)
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


@router.post("/levels")
def create_level(body: LevelBody, _admin=Depends(verify_admin), db: Session = Depends(get_db)):
    body.validate_quotas()
    level = UserLevel(**body.model_dump())
    db.add(level)
    db.commit()
    db.refresh(level)
    return {"id": level.id, "ok": True}


@router.put("/levels/{level_id}")
def update_level(level_id: int, body: LevelBody, _admin=Depends(verify_admin), db: Session = Depends(get_db)):
    body.validate_quotas()
    l = db.query(UserLevel).filter(UserLevel.id == level_id).first()
    if not l:
        raise HTTPException(status_code=404, detail="等级不存在")
    previous_limits = {
        "max_recipes": l.max_recipes or 0,
        "max_works": l.max_works or 0,
        "max_views": l.max_views or 0,
    }
    values = body.model_dump()
    if level_id in SYSTEM_LEVEL_NAMES:
        values["name"] = SYSTEM_LEVEL_NAMES[level_id]
    for k, v in values.items():
        setattr(l, k, v)
    from services.user_quota import sync_level_quotas
    synced_users = sync_level_quotas(db, level_id, previous_limits, values)
    db.commit()
    return {"ok": True, "synced_users": synced_users}


@router.delete("/levels/{level_id}")
def delete_level(level_id: int, _admin=Depends(verify_admin), db: Session = Depends(get_db)):
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
def stats(_admin=Depends(verify_admin), db: Session = Depends(get_db)):
    return {
        "user_count": db.query(User).count(),
        "recipe_count": db.query(Recipe).count(),
        "work_count": db.query(Work).count(),
        "muted_count": db.query(User).filter(User.is_muted == True).count(),
    }


@router.get("/verification-settings")
def get_verification_config(_admin=Depends(verify_admin), db: Session = Depends(get_db)):
    return get_verification_settings(db, mask_sensitive=True)


@router.put("/verification-settings")
def update_verification_config(
    body: VerificationSettingsBody,
    _admin=Depends(verify_admin),
    db: Session = Depends(get_db),
):
    if body.verification_account_mode not in ("sms", "email", "either"):
        raise HTTPException(status_code=400, detail="注册/登录验证方式不正确")
    if body.verification_channel not in ("debug", "email", "sms"):
        raise HTTPException(status_code=400, detail="验证码渠道不正确")
    return save_verification_settings(db, body.model_dump())


# ========= 作品搜索配置 =========

@router.get("/work-search-settings")
def get_work_search_settings(_admin=Depends(verify_admin), db: Session = Depends(get_db)):
    return {
        "temperature_ranges": _ensure_json_setting(db, "work_search_temperature_ranges", TEMPERATURE_RANGE_CONFIG),
        "color_ranges": _ensure_json_setting(db, "work_search_color_ranges", get_color_range_config()),
    }
@router.put("/work-search-settings")
def update_work_search_settings(
    body: WorkSearchSettingsBody,
    _admin=Depends(verify_admin),
    db: Session = Depends(get_db),
):
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
def list_work_attributes(_admin=Depends(verify_admin), db: Session = Depends(get_db)):
    """获取所有作品属性选项，按 category 分组"""
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
def create_work_attribute(body: WorkAttributeOptionBody, _admin=Depends(verify_admin), db: Session = Depends(get_db)):
    opt = WorkAttributeOption(category=body.category, value=body.value, sort_order=body.sort_order)
    db.add(opt)
    db.commit()
    db.refresh(opt)
    return {"id": opt.id, "ok": True}


@router.put("/work-attributes/{opt_id}")
def update_work_attribute(opt_id: int, body: WorkAttributeOptionBody, _admin=Depends(verify_admin), db: Session = Depends(get_db)):
    opt = db.query(WorkAttributeOption).filter(WorkAttributeOption.id == opt_id).first()
    if not opt:
        raise HTTPException(status_code=404, detail="选项不存在")
    opt.category = body.category
    opt.value = body.value
    opt.sort_order = body.sort_order
    db.commit()
    return {"ok": True}


@router.delete("/work-attributes/{opt_id}")
def delete_work_attribute(opt_id: int, _admin=Depends(verify_admin), db: Session = Depends(get_db)):
    opt = db.query(WorkAttributeOption).filter(WorkAttributeOption.id == opt_id).first()
    if not opt:
        raise HTTPException(status_code=404, detail="选项不存在")
    db.delete(opt)
    db.commit()
    return {"ok": True}


# ========= 公开接口（不含管理验证）=========

@router.get("/public/work-attributes")
def get_public_work_attributes(db: Session = Depends(get_db)):
    """公开查询，供配方和作品发布页加载可输入的属性建议。"""
    options = db.query(WorkAttributeOption).order_by(WorkAttributeOption.category, WorkAttributeOption.sort_order).all()
    grouped = {}
    for opt in options:
        grouped.setdefault(opt.category, []).append(opt.value)
    return grouped


@router.get("/materials")
def admin_list_materials(
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    duplicate_only: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=200),
    db: Session = Depends(get_db),
    _=Depends(verify_admin),
):
    """管理员查看原材料列表"""
    q = db.query(Material).filter(Material.is_active.is_(True))
    if status:
        q = q.filter(Material.status == status)
    if duplicate_only:
        duplicate_family_ids = db.query(Material.family_id).filter(
            Material.is_active.is_(True), Material.family_id.isnot(None),
        ).group_by(Material.family_id).having(func.count(Material.id) > 1)
        q = q.filter(Material.family_id.in_(duplicate_family_ids))
    search_whitespace = (" ", "\u3000", "\t", "\r", "\n", "\v", "\f", "\u00a0")
    normalized_search = search or ""
    for whitespace in search_whitespace:
        normalized_search = normalized_search.replace(whitespace, "")
    if normalized_search:
        def without_spaces(column):
            normalized = column
            for whitespace in search_whitespace:
                normalized = func.replace(normalized, whitespace, "")
            return normalized

        keyword = f"%{normalized_search}%"
        q = q.filter(
            without_spaces(Material.name).like(keyword) |
            without_spaces(Material.name_en).like(keyword)
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
                "family_id": m.family_id,
                "name": m.name,
                "variant_name": m.variant_name or "",
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
                "status": m.status,
                "created_from": m.created_from or "",
                "is_default": bool(m.family_id and db.query(MaterialFamily.default_material_id).filter(
                    MaterialFamily.id == m.family_id,
                ).scalar() == m.id),
                "variant_count": db.query(func.count(Material.id)).filter(
                    Material.family_id == m.family_id, Material.is_active.is_(True),
                ).scalar() if m.family_id else 1,
                "affected_recipe_count": db.query(func.count(func.distinct(RecipeIngredient.recipe_id))).filter(
                    RecipeIngredient.material_id == m.id,
                ).scalar() or 0,
                "owner": ({"id": m.user_id, "name": db.query(User.nickname).filter(User.id == m.user_id).scalar() or ""}
                          if m.user_id else None),
                "review_note": m.review_note or "",
            }
            for m in items
        ],
    }


@router.get("/material-dedup/groups")
def admin_duplicate_material_groups(db: Session = Depends(get_db), _=Depends(verify_admin)):
    groups = duplicate_groups(db)
    return {
        "groups": groups,
        "total": len(groups),
        "exact": sum(item["duplicate_type"] == "exact" for item in groups),
        "conflict": sum(item["duplicate_type"] == "conflict" for item in groups),
    }


@router.get("/material-families/{family_id}")
def admin_material_family(family_id: int, db: Session = Depends(get_db), _=Depends(verify_admin)):
    family = db.query(MaterialFamily).filter(MaterialFamily.id == family_id).first()
    if not family:
        raise HTTPException(status_code=404, detail="材料族不存在")
    variants = db.query(Material).filter(Material.family_id == family_id, Material.is_active.is_(True)).order_by(Material.id).all()
    return {
        "id": family.id,
        "name": family.canonical_name,
        "default_material_id": family.default_material_id,
        "variants": [dict(catalog_payload(item),
                          affected_recipe_count=len(affected_recipe_ids(db, item.id)),
                          is_default=item.id == family.default_material_id)
                     for item in variants],
    }


@router.post("/materials/{material_id}/set-default")
def admin_set_default_material(material_id: int, db: Session = Depends(get_db), _=Depends(verify_admin)):
    material = db.query(Material).filter(Material.id == material_id, Material.is_active.is_(True)).first()
    if not material or not material.family_id:
        raise HTTPException(status_code=404, detail="材料或材料族不存在")
    if material.status != "recalculated" or material.data_quality_status == "disabled":
        raise HTTPException(status_code=409, detail="只有审核并重算完成的有效材料才能设为默认")
    family = db.query(MaterialFamily).filter(MaterialFamily.id == material.family_id).first()
    family.default_material_id = material.id
    db.commit()
    backfill = backfill_recipe_material_links(db, family_id=family.id)
    recalculation = recalculate_material_recipes(db, material)
    return {
        "message": "已设为默认变体并重新计算关联配方",
        "material_id": material.id,
        "backfill": backfill,
        "recalculation": recalculation,
    }


@router.post("/material-dedup/backfill-links")
def admin_backfill_material_links(db: Session = Depends(get_db), _=Depends(verify_admin)):
    result = backfill_recipe_material_links(db)
    return {"message": f"已关联 {result['linked']} 条历史配料", **result}


@router.post("/materials/{source_id}/merge")
def admin_merge_material(
    source_id: int,
    body: dict,
    db: Session = Depends(get_db),
    admin: User = Depends(verify_admin),
):
    source = db.query(Material).filter(Material.id == source_id).first()
    target = db.query(Material).filter(Material.id == int(body.get("target_material_id") or 0)).first()
    if not source or not target:
        raise HTTPException(status_code=404, detail="源材料或目标材料不存在")
    composition_changed = (
        (source.composition_fingerprint or composition_fingerprint(source))
        != (target.composition_fingerprint or composition_fingerprint(target))
    )
    try:
        log = merge_materials(
            db, source=source, target=target, admin_user_id=admin.id,
            reason=str(body.get("reason") or "管理员合并"),
            require_exact=bool(body.get("require_exact", False)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    recalculation = recalculate_material_recipes(db, target) if composition_changed else {
        "total": 0, "succeeded": 0, "failed": 0, "failures": [],
    }
    return {
        "message": "材料已软合并", "merge_log_id": log.id,
        "target_material_id": target.id, "recalculation": recalculation,
    }


@router.post("/material-dedup/auto-merge-exact")
def admin_auto_merge_exact(db: Session = Depends(get_db), admin: User = Depends(verify_admin)):
    merged = []
    for group in duplicate_groups(db):
        for cluster in group["exact_clusters"]:
            variants = db.query(Material).filter(Material.id.in_(cluster), Material.is_active.is_(True)).all()
            if len(variants) < 2:
                continue
            target = max(variants, key=lambda item: (
                item.status == "recalculated",
                sum(getattr(item, field, None) is not None for field in (
                    "sio2", "al2o3", "fe2o3", "tio2", "cao", "mgo", "na2o", "k2o",
                    "zno", "b2o3", "p2o5", "li2o", "mno2", "coo", "sno2", "cuo",
                    "cr2o3", "pbo", "bao", "sro", "loi",
                )),
                -item.id,
            ))
            for source in variants:
                if source.id == target.id:
                    continue
                log = merge_materials(
                    db, source=source, target=target, admin_user_id=admin.id,
                    reason="自动合并完全相同的成分指纹", require_exact=True,
                )
                merged.append({"source_id": source.id, "target_id": target.id, "log_id": log.id})
    db.commit()
    return {"message": f"已合并 {len(merged)} 条完全重复材料", "merged": merged}


@router.put("/materials/{material_id}")
def admin_update_material(
    material_id: int,
    body: dict,
    db: Session = Depends(get_db),
    admin: User = Depends(verify_admin),
):
    material = db.query(Material).filter(Material.id == material_id, Material.is_active.is_(True)).first()
    if not material:
        raise HTTPException(status_code=404, detail="材料不存在")
    cleaned = clean_molecule_data(body, partial=True)
    revision = db.query(MaterialRevision).filter(
        MaterialRevision.material_id == material.id,
        MaterialRevision.status.in_(("initial", "submitted")),
    ).order_by(MaterialRevision.id.desc()).first()
    payload = json.loads(revision.payload_json or "{}") if revision else clean_molecule_data(catalog_payload(material), partial=True)
    payload.update(cleaned)
    if not revision:
        revision = MaterialRevision(material_id=material.id, submitted_by=admin.id)
        db.add(revision)
    revision.payload_json = json.dumps(payload, ensure_ascii=False, default=str)
    revision.status = "submitted"
    revision.submitted_by = admin.id
    material.status = "submitted"
    material.submitted_at = datetime.now(timezone.utc)
    if "variant_name" in body:
        material.variant_name = str(body.get("variant_name") or "").strip()[:200]
    db.commit()
    return {**catalog_payload(material), "draft": payload}


@router.post("/materials/{material_id}/approve-and-recalculate")
def admin_approve_and_recalculate(
    material_id: int,
    body: dict | None = None,
    db: Session = Depends(get_db),
    admin: User = Depends(verify_admin),
):
    material = db.query(Material).filter(Material.id == material_id, Material.is_active.is_(True)).first()
    if not material:
        raise HTTPException(status_code=404, detail="材料不存在")
    revision = db.query(MaterialRevision).filter(
        MaterialRevision.material_id == material.id,
        MaterialRevision.status == "submitted",
    ).order_by(MaterialRevision.id.desc()).first()
    payload = json.loads(revision.payload_json or "{}") if revision else {}
    if body:
        payload.update(body.get("data") or {})
    cleaned = clean_molecule_data(payload, partial=True)
    if not any(cleaned.get(field) not in (None, 0, 0.0) for field in (
        "sio2", "al2o3", "fe2o3", "tio2", "cao", "mgo", "na2o", "k2o",
        "zno", "b2o3", "p2o5", "li2o", "mno2", "coo", "sno2", "cuo", "cr2o3", "pbo", "bao", "sro",
    )):
        raise HTTPException(status_code=400, detail="材料没有可用于计算的氧化物数据")
    for field, value in cleaned.items():
        setattr(material, field, value)
    material.status = "recalculated"  # calculation must be allowed to consume the approved values
    material.reviewed_by = admin.id
    material.reviewed_at = datetime.now(timezone.utc)
    material.review_note = str((body or {}).get("review_note") or "")
    material.composition_fingerprint = composition_fingerprint(material)
    if revision:
        revision.status = "approved"
    prepare_material(db, material)
    family = db.query(MaterialFamily).filter(MaterialFamily.id == material.family_id).first()
    if family and not family.default_material_id:
        family.default_material_id = material.id
    db.commit()
    result = recalculate_material_recipes(db, material)
    material.status = "recalculated" if result["failed"] == 0 else "submitted"
    material.recalculated_at = datetime.now(timezone.utc) if result["failed"] == 0 else None
    db.commit()
    return {"message": "审核及重算完成" if result["failed"] == 0 else "部分配方重算失败", "result": result, "status": material.status}


@router.post("/materials/{material_id}/reject")
def admin_reject_material(
    material_id: int,
    body: dict,
    db: Session = Depends(get_db),
    admin: User = Depends(verify_admin),
):
    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        raise HTTPException(status_code=404, detail="材料不存在")
    revision = db.query(MaterialRevision).filter(
        MaterialRevision.material_id == material.id, MaterialRevision.status == "submitted",
    ).order_by(MaterialRevision.id.desc()).first()
    if revision:
        revision.status = "initial"
    material.status = "initial"
    material.reviewed_by = admin.id
    material.reviewed_at = datetime.now(timezone.utc)
    material.review_note = str(body.get("reason") or "请完善材料数据")[:2000]
    db.commit()
    return {"message": "已退回修改", "status": material.status}


@router.get("/materials/{material_id}/affected-recipes")
def admin_affected_recipes(material_id: int, db: Session = Depends(get_db), _=Depends(verify_admin)):
    rows = db.query(Recipe).join(RecipeIngredient, RecipeIngredient.recipe_id == Recipe.id).filter(
        RecipeIngredient.material_id == material_id,
    ).distinct().order_by(Recipe.id.desc()).all()
    return [{"id": item.id, "recipe_no": item.recipe_no, "title": item.title, "user_id": item.user_id} for item in rows]


@router.post("/materials/{material_id}/disable")
def admin_disable_material(material_id: int, db: Session = Depends(get_db), _=Depends(verify_admin)):
    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        raise HTTPException(status_code=404, detail="材料不存在")
    material.data_quality_status = "disabled"
    db.commit()
    return {"message": "已禁用，该材料不再参与新的 Seger 计算"}


@router.get("/material-merge-logs")
def admin_material_merge_logs(db: Session = Depends(get_db), _=Depends(verify_admin)):
    rows = db.query(MaterialMergeLog).order_by(MaterialMergeLog.id.desc()).limit(200).all()
    return [{
        "id": row.id, "source_material_id": row.source_material_id,
        "target_material_id": row.target_material_id, "reason": row.reason,
        "merged_by": row.merged_by, "merged_at": row.merged_at,
        "rolled_back_at": row.rolled_back_at,
    } for row in rows]


@router.post("/material-merge-logs/{log_id}/rollback")
def admin_rollback_material_merge(log_id: int, db: Session = Depends(get_db), _=Depends(verify_admin)):
    log = db.query(MaterialMergeLog).filter(MaterialMergeLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="合并记录不存在")
    try:
        result = rollback_material_merge(db, log)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"message": "材料合并已回滚", **result}


@router.delete("/materials/{material_id}")
def admin_delete_material(
    material_id: int,
    db: Session = Depends(get_db),
    _=Depends(verify_admin),
):
    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        raise HTTPException(status_code=404, detail="材料不存在")

    affected = affected_recipe_ids(db, material_id)
    if affected:
        raise HTTPException(status_code=409, detail=f"该材料影响 {len(affected)} 个配方，请先合并或重新关联材料")
    family = db.query(MaterialFamily).filter(MaterialFamily.id == material.family_id).first() if material.family_id else None
    if family and family.default_material_id == material.id:
        raise HTTPException(status_code=409, detail="该材料是材料族默认变体，请先设置其他默认变体")

    deleted_substitutions = db.query(MaterialSubstitution).filter(or_(
        MaterialSubstitution.source_material_id == material_id,
        MaterialSubstitution.target_material_id == material_id,
    )).delete(synchronize_session=False)
    material.is_active = False
    material.data_quality_status = "disabled"
    db.commit()
    return {
        "message": "材料已停用",
        "deleted_substitutions": deleted_substitutions,
    }


# ========= 投诉处理 =========

class AdminComplaintReplyBody(BaseModel):
    content: str


class AdminComplaintClosedBody(BaseModel):
    closed: bool


def _parse_filter_date(value: Optional[str], end_of_day: bool = False) -> Optional[datetime]:
    if not value:
        return None
    try:
        day = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD") from exc
    return datetime.combine(day, time.max if end_of_day else time.min)


@router.get("/complaints")
def admin_list_complaints(
    q: str = "",
    answered: Optional[bool] = None,
    resolved: Optional[bool] = None,
    closed: Optional[bool] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _admin=Depends(verify_admin),
    db: Session = Depends(get_db),
):
    query = db.query(Complaint).join(User, User.id == Complaint.user_id)
    keyword = q.strip()
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(or_(
            Complaint.content.like(like),
            User.nickname.like(like),
            User.username.like(like),
        ))

    has_thread_reply = exists().where(ComplaintReply.complaint_id == Complaint.id)
    has_legacy_reply = and_(Complaint.reply.is_not(None), Complaint.reply != "")
    if answered is True:
        query = query.filter(or_(has_legacy_reply, has_thread_reply))
    elif answered is False:
        query = query.filter(~or_(has_legacy_reply, has_thread_reply))
    if resolved is not None:
        query = query.filter(Complaint.is_resolved.is_(resolved))
    if closed is not None:
        query = query.filter(Complaint.is_closed.is_(closed))

    start = _parse_filter_date(date_from)
    end = _parse_filter_date(date_to, end_of_day=True)
    if start:
        query = query.filter(Complaint.created_at >= start)
    if end:
        query = query.filter(Complaint.created_at <= end)

    total = query.count()
    items = (
        query.order_by(Complaint.created_at.desc(), Complaint.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "results": [serialize_complaint(item, db, include_user=True) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/complaints/{complaint_id}")
def admin_get_complaint(
    complaint_id: int,
    _admin=Depends(verify_admin),
    db: Session = Depends(get_db),
):
    item = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="反馈不存在")
    return serialize_complaint(item, db, include_user=True)


@router.post("/complaints/{complaint_id}/replies")
def admin_reply_complaint(
    complaint_id: int,
    body: AdminComplaintReplyBody,
    request: Request,
    _admin=Depends(verify_admin),
    db: Session = Depends(get_db),
):
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="回复内容不能为空")
    item = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="反馈不存在")

    token = token_from_request(request)
    payload = decode_access_token(token)
    admin_id = int(payload.get("sub", 0))
    reply = ComplaintReply(
        complaint_id=item.id,
        admin_id=admin_id,
        content=content[:1000],
    )
    db.add(reply)
    item.reply = content[:1000]
    item.admin_id = admin_id
    item.replied_at = datetime.utcnow()
    item.status = "resolved" if item.is_resolved else "replied"
    db.commit()
    db.refresh(item)
    add_notification(
        db, user_id=item.user_id, from_user_id=admin_id, type="complaint_reply",
        complaint_id=item.id, content=f"你的投诉建议 #{item.id} 收到了回复",
    )
    return serialize_complaint(item, db, include_user=True)


@router.put("/complaints/{complaint_id}/closed")
def admin_update_complaint_closed(
    complaint_id: int,
    body: AdminComplaintClosedBody,
    request: Request,
    _admin=Depends(verify_admin),
    db: Session = Depends(get_db),
):
    item = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="反馈不存在")

    token = token_from_request(request)
    payload = decode_access_token(token)
    admin_id = int(payload.get("sub", 0))
    item.is_closed = body.closed
    item.closed_at = datetime.utcnow() if body.closed else None
    item.closed_by = admin_id if body.closed else None
    db.commit()
    db.refresh(item)
    return serialize_complaint(item, db, include_user=True)
