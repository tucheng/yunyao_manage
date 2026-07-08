from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from database import get_db
from models import AppSetting, Work, Recipe, User, Favorite, WorkComment, FiringCurve, Like
from sqlalchemy import func, inspect, text
from datetime import datetime
import json
from color_names import color_name_in_range, get_color_range_config, get_glaze_colors_data

router = APIRouter(prefix="/works", tags=["作品"])


TEMPERATURE_RANGE_CONFIG = [
    {
        "value": "low",
        "label": "低温",
        "min": 0,
        "max": 1099,
        "description": "低于 1100℃，常见于低温釉、彩绘和二次烧成。",
    },
    {
        "value": "middle",
        "label": "中温",
        "min": 1100,
        "max": 1249,
        "description": "1100-1249℃，常见于中温釉和日用陶瓷烧成。",
    },
    {
        "value": "high",
        "label": "高温",
        "min": 1250,
        "max": 1450,
        "description": "1250℃ 及以上，常见于高温瓷、青瓷和部分还原烧。",
    },
]

SURFACE_OPTIONS = ["亮光", "丝光", "蜡光", "柔光", "无光", "磨砂"]
TRANSPARENCY_OPTIONS = ["高透", "微透", "半透", "不透"]
KILN_TYPE_OPTIONS = ["电窑", "气窑", "柴窑", "乐烧"]
HAS_RECIPE_OPTIONS = [
    {"value": "yes", "label": "有配方"},
    {"value": "no", "label": "无配方"},
]


# ---------- 关注动态 ----------


@router.get("/feed/following")
def following_works(
    user_id: int = Query(...),
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    """获取关注用户发布的作品"""
    from models import Follow
    following = db.query(Follow.followed_id).filter(
        Follow.follower_id == user_id
    ).all()
    followed_ids = [f.followed_id for f in following]
    if not followed_ids:
        return []

    query = db.query(Work).filter(Work.user_id.in_(followed_ids))
    rows = (
        query.order_by(Work.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    work_ids = [w.id for w in rows]
    favorited_ids = set()
    liked_ids = set()
    if work_ids:
        for row in db.query(Favorite.work_id).filter(
            Favorite.user_id == user_id, Favorite.work_id.in_(work_ids)
        ).all():
            favorited_ids.add(row.work_id)
        for row in db.query(Like.work_id).filter(
            Like.user_id == user_id, Like.work_id.in_(work_ids)
        ).all():
            liked_ids.add(row.work_id)

    result = []
    for work in rows:
        user = db.query(User).filter(User.id == work.user_id).first()
        result.append({
            "id": work.id,
            "user_id": work.user_id,
            "nickname": user.nickname if user else f"用户{work.user_id}",
            "avatar": user.avatar if user else "",
            "recipe_id": work.recipe_id,
            "image": _image_url(work.image),
            "images": [_image_url(u) for u in (json.loads(work.images) if work.images else []) if u],
            "description": work.description or "",
            "body_material": work.body_material or "",
            "kiln_type": work.kiln_type or "",
            "temperature": work.temperature or "",
            "created_at": work.created_at,
            "comment_count": db.query(WorkComment).filter(WorkComment.work_id == work.id).count(),
            "favorite_count": db.query(Favorite).filter(Favorite.work_id == work.id).count(),
            "is_favorited": work.id in favorited_ids,
            "likes": work.likes or 0,
            "is_liked": work.id in liked_ids,
        })
    return result


def _image_url(image: str) -> str:
    image = (image or "").strip()
    if not image:
        return ""
    if image.startswith(("http://", "https://", "/")):
        return image
    return f"/uploads/{image}"


# 初始化表



def _temperature_value(raw: str):
    if not raw:
        return None
    digits = ""
    for ch in str(raw):
        if ch.isdigit() or (ch == "." and "." not in digits):
            digits += ch
        elif digits:
            break
    if not digits:
        return None
    try:
        return float(digits)
    except ValueError:
        return None


def _get_json_setting(db: Session, key: str, default):
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if not row or not row.value:
        return default
    try:
        value = json.loads(row.value)
    except Exception:
        return default
    return value if isinstance(value, type(default)) else default


def _get_temperature_ranges(db: Session) -> list:
    return _get_json_setting(db, "work_search_temperature_ranges", TEMPERATURE_RANGE_CONFIG)


def _get_color_ranges(db: Session) -> list:
    return _get_json_setting(db, "work_search_color_ranges", get_color_range_config())


def _temperature_in_range(raw: str, range_value: str, temperature_ranges: list) -> bool:
    temp = _temperature_value(raw)
    if temp is None:
        return False
    for item in temperature_ranges:
        if item["value"] == range_value:
            return item["min"] <= temp <= item["max"]
    return False


def _color_name_in_ranges(name: str, range_value: str, color_ranges: list) -> bool:
    if not name or not range_value:
        return False
    for item in color_ranges:
        if item.get("value") == range_value:
            return name in (item.get("names") or [])
    return color_name_in_range(name, range_value)


def _work_has_color_range(work: Work, range_value: str, color_ranges: list) -> bool:
    if not range_value:
        return True
    try:
        colors = json.loads(work.glaze_colors) if work.glaze_colors else []
    except Exception:
        colors = []
    if not isinstance(colors, list):
        return False
    return any(_color_name_in_ranges((item or {}).get("name", ""), range_value, color_ranges) for item in colors)


def _same_filter_value(raw: str, selected: str) -> bool:
    selected_value = str(selected or "").strip()
    if not selected_value:
        return True
    raw_value = str(raw or "").strip()
    if not raw_value:
        return False
    return raw_value == selected_value


def _work_matches_search_filters(
    work: Work,
    recipe: Recipe,
    body_material: str,
    kiln_type: str,
    temperature_range: str,
    surface: str,
    transparency: str,
    color_range: str,
    has_recipe: str,
    temperature_ranges: list,
    color_ranges: list,
) -> bool:
    """All selected work-search filters are AND conditions."""
    if body_material and not _same_filter_value(work.body_material, body_material):
        return False
    if kiln_type and not _same_filter_value(work.kiln_type, kiln_type):
        return False
    if surface and not _same_filter_value(work.surface, surface):
        return False
    if transparency and not _same_filter_value(work.transparency, transparency):
        return False
    if temperature_range and not _temperature_in_range(work.temperature, temperature_range, temperature_ranges):
        return False
    if color_range and not _work_has_color_range(work, color_range, color_ranges):
        return False
    has_linked_recipe = recipe is not None
    if has_recipe == "yes" and not has_linked_recipe:
        return False
    if has_recipe == "no" and has_linked_recipe:
        return False
    return True


@router.get("/search/config")
def get_work_search_config(db: Session = Depends(get_db)):
    """作品高级搜索配置。"""
    from models import WorkAttributeOption
    # 从 DB 读取作品属性选项
    attr_options = db.query(WorkAttributeOption).order_by(WorkAttributeOption.category, WorkAttributeOption.sort_order).all()
    body_materials = [o.value for o in attr_options if o.category == 'body_material']
    kiln_types = [o.value for o in attr_options if o.category == 'kiln_type']
    surfaces = [o.value for o in attr_options if o.category == "surface"]
    transparencies = [o.value for o in attr_options if o.category == "transparency"]
    return {
        "body_materials": body_materials,
        "kiln_types": kiln_types or KILN_TYPE_OPTIONS,
        "temperature_ranges": _get_temperature_ranges(db),
        "surfaces": surfaces or SURFACE_OPTIONS,
        "transparencies": transparencies or TRANSPARENCY_OPTIONS,
        "color_ranges": _get_color_ranges(db),
        "has_recipe_options": HAS_RECIPE_OPTIONS,
    }


@router.get("/count")
def count_works(
    recipe_id: int = 0,
    user_id: int = 0,
    q: str = "",
    body_material: str = "",
    kiln_type: str = "",
    temperature_range: str = "",
    surface: str = "",
    transparency: str = "",
    color_range: str = "",
    has_recipe: str = "",
    db: Session = Depends(get_db),
):
    """Count works with the same AND search-filter rules as /works/."""
    query = (
        db.query(Work, User, Recipe)
        .outerjoin(User, Work.user_id == User.id)
        .outerjoin(Recipe, Work.recipe_id == Recipe.id)
    )
    if recipe_id > 0:
        query = query.filter(Work.recipe_id == recipe_id)
    if user_id > 0:
        query = query.filter(Work.user_id == user_id)
    if q:
        like = f"%{q}%"
        query = query.filter(
            Work.description.like(like)
            | Work.body_material.like(like)
            | Work.kiln_type.like(like)
            | Work.temperature.like(like)
            | Work.surface.like(like)
            | Work.transparency.like(like)
            | User.nickname.like(like)
        )

    has_search_filters = any([
        body_material,
        kiln_type,
        temperature_range,
        surface,
        transparency,
        color_range,
        has_recipe,
    ])
    if not has_search_filters:
        return {"count": query.count()}

    temperature_ranges = _get_temperature_ranges(db)
    color_ranges = _get_color_ranges(db)
    count = 0
    for work, _, recipe in query.all():
        if _work_matches_search_filters(
            work,
            recipe,
            body_material,
            kiln_type,
            temperature_range,
            surface,
            transparency,
            color_range,
            has_recipe,
            temperature_ranges,
            color_ranges,
        ):
            count += 1
    return {"count": count}


@router.get("/")
def list_works(
    recipe_id: int = 0,
    user_id: int = 0,
    current_user_id: int = 0,
    q: str = "",
    body_material: str = "",
    kiln_type: str = "",
    temperature_range: str = "",
    surface: str = "",
    transparency: str = "",
    color_range: str = "",
    has_recipe: str = "",
    page: int = 1,
    page_size: int = Query(default=20, alias="page_size"),
    db: Session = Depends(get_db),
):
    """列出作品（优化：JOIN替代N+1查询）"""
    comment_counts = (
        db.query(WorkComment.work_id, func.count(WorkComment.id).label("comment_count"))
        .group_by(WorkComment.work_id)
        .subquery()
    )
    favorite_counts = (
        db.query(Favorite.work_id, func.count(Favorite.id).label("favorite_count"))
        .group_by(Favorite.work_id)
        .subquery()
    )
    query = (
        db.query(Work, User, Recipe, comment_counts.c.comment_count, favorite_counts.c.favorite_count)
        .outerjoin(User, Work.user_id == User.id)
        .outerjoin(Recipe, Work.recipe_id == Recipe.id)
        .outerjoin(comment_counts, Work.id == comment_counts.c.work_id)
        .outerjoin(favorite_counts, Work.id == favorite_counts.c.work_id)
    )
    if recipe_id > 0:
        query = query.filter(Work.recipe_id == recipe_id)
    if user_id > 0:
        query = query.filter(Work.user_id == user_id)
    if q:
        like = f"%{q}%"
        query = query.filter(
            Work.description.like(like)
            | Work.body_material.like(like)
            | Work.kiln_type.like(like)
            | Work.temperature.like(like)
            | Work.surface.like(like)
            | Work.transparency.like(like)
            | User.nickname.like(like)
        )
    ordered_query = query.order_by(Work.created_at.desc())
    has_search_filters = any([
        body_material,
        kiln_type,
        temperature_range,
        surface,
        transparency,
        color_range,
        has_recipe,
    ])
    if has_search_filters:
        temperature_ranges = _get_temperature_ranges(db)
        color_ranges = _get_color_ranges(db)
        all_rows = ordered_query.all()
        filtered_rows = []
        for row in all_rows:
            work, _, recipe, *_ = row
            if _work_matches_search_filters(
                work,
                recipe,
                body_material,
                kiln_type,
                temperature_range,
                surface,
                transparency,
                color_range,
                has_recipe,
                temperature_ranges,
                color_ranges,
            ):
                filtered_rows.append(row)
        start = (page - 1) * page_size
        rows = filtered_rows[start:start + page_size]
    else:
        rows = (
            ordered_query
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

    work_ids = [work.id for work, *_ in rows]
    favorited_ids = set()
    liked_ids = set()
    if current_user_id > 0 and work_ids:
        favorited_ids = {
            row.work_id
            for row in db.query(Favorite.work_id)
            .filter(Favorite.user_id == current_user_id, Favorite.work_id.in_(work_ids))
            .all()
        }
        liked_ids = {
            row.work_id
            for row in db.query(Like.work_id)
            .filter(Like.user_id == current_user_id, Like.work_id.in_(work_ids))
            .all()
        }

    result = []
    for work, user, recipe, comment_count, favorite_count in rows:
        # 解析多图
        imgs = []
        if work.images:
            try:
                imgs = json.loads(work.images)
            except:
                imgs = []
        if not imgs and work.image:
            imgs = [work.image]
        result.append({
            "id": work.id,
            "user_id": work.user_id,
            "nickname": user.nickname if user else f"用户{work.user_id}",
            "avatar": user.avatar if user else "",
            "recipe_id": work.recipe_id,
            "recipe_title": recipe.title if recipe else "",
            "image": _image_url(work.image),
            "images": [_image_url(u) for u in imgs if u],
            "description": work.description or "",
            "body_material": work.body_material or "",
            "kiln_type": work.kiln_type or "",
            "kiln_type_other": work.kiln_type_other or "",
            "temperature": work.temperature or "",
            "created_at": work.created_at,
            "comment_count": comment_count or 0,
            "favorite_count": favorite_count or 0,
            "is_favorited": work.id in favorited_ids,
            "likes": work.likes or 0,
            "glaze_colors": json.loads(work.glaze_colors) if work.glaze_colors else [],
            "surface": work.surface or "",
            "transparency": work.transparency or "",
            "curve_id": work.curve_id,
        })
    return result


@router.put("/{work_id}")
def update_work(work_id: int, data: dict, db: Session = Depends(get_db)):
    """更新作品"""
    work = db.query(Work).filter(Work.id == work_id).first()
    if not work:
        raise HTTPException(status_code=404, detail="作品不存在")

    user_id = data.get("user_id", 0)
    if not user_id or work.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权编辑")

    image = (data.get("image") or "").strip()
    recipe_id = data.get("recipe_id") or None
    description = data.get("description", "")
    body_material = data.get("body_material", "")
    kiln_type = data.get("kiln_type", "")
    kiln_type_other = data.get("kiln_type_other", "")
    temperature = data.get("temperature", "")
    surface = data.get("surface", "")
    transparency = data.get("transparency", "")
    curve_id = data.get("curve_id") or None

    # 处理多图
    images_raw = data.get("images") or []
    if isinstance(images_raw, str):
        try:
            images_raw = json.loads(images_raw)
        except:
            images_raw = []
    if not isinstance(images_raw, list):
        images_raw = [image] if image else []
    if image and image not in images_raw:
        images_raw.insert(0, image)

    # 处理釉色
    glaze_colors_raw = data.get("glaze_colors") or None
    glaze_colors_json = "[]"
    if glaze_colors_raw:
        if isinstance(glaze_colors_raw, list):
            hex_list = []
            for c in glaze_colors_raw:
                if isinstance(c, dict):
                    hex_list.append(c.get("hex", ""))
                elif isinstance(c, str):
                    hex_list.append(c)
                else:
                    hex_list.append(str(c))
            hex_list = [h for h in hex_list if h]
            colors_data = get_glaze_colors_data(hex_list) if hex_list else []
        elif isinstance(glaze_colors_raw, str):
            try:
                parsed = json.loads(glaze_colors_raw)
                if isinstance(parsed, list):
                    hex_list = []
                    for c in parsed:
                        if isinstance(c, dict):
                            hex_list.append(c.get("hex", ""))
                        elif isinstance(c, str):
                            hex_list.append(c)
                        else:
                            hex_list.append(str(c))
                    hex_list = [h for h in hex_list if h]
                    colors_data = get_glaze_colors_data(hex_list) if hex_list else []
                else:
                    colors_data = []
            except:
                colors_data = []
        else:
            colors_data = []
        glaze_colors_json = json.dumps(colors_data, ensure_ascii=False)

    work.image = image
    work.images = json.dumps(images_raw, ensure_ascii=False)
    work.description = description
    work.body_material = body_material
    work.kiln_type = kiln_type
    work.kiln_type_other = kiln_type_other
    work.temperature = temperature
    work.surface = surface
    work.transparency = transparency
    work.curve_id = curve_id
    work.glaze_colors = glaze_colors_json
    if recipe_id is not None:
        old_recipe_id = work.recipe_id
        work.recipe_id = recipe_id
        if old_recipe_id != recipe_id:
            if old_recipe_id:
                db.query(Recipe).filter(Recipe.id == old_recipe_id).update({"work_count": Recipe.work_count - 1})
            if recipe_id:
                db.query(Recipe).filter(Recipe.id == recipe_id).update({"work_count": Recipe.work_count + 1})

    db.commit()
    db.refresh(work)
    return {"id": work.id, "message": "更新成功"}


@router.post("/")
def create_work(
    data: dict,
    db: Session = Depends(get_db),
):
    """发布作品"""
    image = (data.get("image") or "").strip()
    user_id = data.get("user_id", 0)
    recipe_id = data.get("recipe_id") or None
    description = data.get("description", "")
    body_material = data.get("body_material", "")
    kiln_type = data.get("kiln_type", "")
    kiln_type_other = data.get("kiln_type_other", "")
    temperature = data.get("temperature", "")
    surface = data.get("surface", "")
    transparency = data.get("transparency", "")
    curve_id = data.get("curve_id") or None
    
    if not image:
        raise HTTPException(status_code=400, detail="作品图片不能为空")
    
    if not user_id:
        raise HTTPException(status_code=400, detail="用户未登录")

    # 处理多图
    images_raw = data.get("images") or []
    if isinstance(images_raw, str):
        try:
            images_raw = json.loads(images_raw)
        except:
            images_raw = []
    if not isinstance(images_raw, list):
        images_raw = [image] if image else []
    if image and image not in images_raw:
        images_raw.insert(0, image)

    # 处理釉色数据
    glaze_colors_raw = data.get("glaze_colors") or None
    glaze_colors_json = "[]"
    if glaze_colors_raw:
        # 支持前端传简洁格式: ["#2E4E7A", "#8B5A2E"]
        if isinstance(glaze_colors_raw, list):
            hex_list = []
            for c in glaze_colors_raw:
                if isinstance(c, dict):
                    hex_list.append(c.get("hex", ""))
                elif isinstance(c, str):
                    hex_list.append(c)
                else:
                    hex_list.append(str(c))
            hex_list = [h for h in hex_list if h]
            colors_data = get_glaze_colors_data(hex_list) if hex_list else []
        elif isinstance(glaze_colors_raw, str):
            try:
                parsed = json.loads(glaze_colors_raw)
                if isinstance(parsed, list):
                    hex_list = []
                    for c in parsed:
                        if isinstance(c, dict):
                            hex_list.append(c.get("hex", ""))
                        elif isinstance(c, str):
                            hex_list.append(c)
                        else:
                            hex_list.append(str(c))
                    hex_list = [h for h in hex_list if h]
                    colors_data = get_glaze_colors_data(hex_list) if hex_list else []
                else:
                    colors_data = []
            except:
                colors_data = []
        else:
            colors_data = []
        glaze_colors_json = json.dumps(colors_data, ensure_ascii=False)

    work = Work(
        user_id=user_id,
        recipe_id=recipe_id,
        image=image,
        images=json.dumps(images_raw, ensure_ascii=False),
        description=description,
        body_material=body_material,
        kiln_type=kiln_type,
        kiln_type_other=kiln_type_other,
        temperature=temperature,
        surface=surface,
        transparency=transparency,
        curve_id=curve_id,
        glaze_colors=glaze_colors_json,
    )
    db.add(work)
    db.commit()
    db.refresh(work)
    # 关联配方时增加作品计数
    if recipe_id:
        db.query(Recipe).filter(Recipe.id == recipe_id).update({"work_count": Recipe.work_count + 1})
        db.commit()
    return {"id": work.id, "message": "发布成功"}


@router.post("/{work_id}/favorite")
def toggle_work_favorite(work_id: int, data: dict, db: Session = Depends(get_db)):
    """点赞/取消点赞作品"""
    user_id = data.get("user_id", 0)
    if not user_id:
        raise HTTPException(status_code=400, detail="请先登录")
    existing = db.query(Favorite).filter(
        Favorite.work_id == work_id,
        Favorite.user_id == user_id,
    ).first()
    if existing:
        db.delete(existing)
        db.commit()
        return {"favorited": False, "favorite_count": db.query(Favorite).filter(Favorite.work_id == work_id).count()}
    fav = Favorite(work_id=work_id, user_id=user_id)
    db.add(fav)
    db.commit()
    return {"favorited": True, "favorite_count": db.query(Favorite).filter(Favorite.work_id == work_id).count()}


@router.post("/{work_id}/like")
def toggle_work_like(work_id: int, user_id: int = Query(...), db: Session = Depends(get_db)):
    work = db.query(Work).filter(Work.id == work_id).first()
    if not work:
        raise HTTPException(status_code=404, detail="作品不存在")
    existing = db.query(Like).filter(
        Like.work_id == work_id,
        Like.user_id == user_id,
    ).first()
    if existing:
        db.delete(existing)
        work.likes = max(0, (work.likes or 1) - 1)
        db.commit()
        return {"liked": False, "likes": work.likes}
    like = Like(work_id=work_id, user_id=user_id)
    db.add(like)
    work.likes = (work.likes or 0) + 1
    db.commit()
    return {"liked": True, "likes": work.likes}


@router.post("/{work_id}/link_recipe")
def link_work_recipe(work_id: int, data: dict, db: Session = Depends(get_db)):
    user_id = data.get("user_id", 0)
    recipe_id = data.get("recipe_id", 0)
    if not user_id or not recipe_id:
        raise HTTPException(status_code=400, detail="缺少用户或配方")
    work = db.query(Work).filter(Work.id == work_id).first()
    if not work:
        raise HTTPException(status_code=404, detail="作品不存在")
    if work.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权修改该作品")
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="配方不存在")
    if recipe.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权关联该配方")
    work.recipe_id = recipe_id
    db.query(Recipe).filter(Recipe.id == recipe_id).update({"work_count": Recipe.work_count + 1})
    db.commit()
    return {"message": "已关联配方", "work_id": work.id, "recipe_id": recipe_id}


@router.get("/{work_id}")
def get_work(work_id: int, current_user_id: int = 0, db: Session = Depends(get_db)):
    """获取单个作品详情（含用户、配方信息）"""
    row = (
        db.query(Work, User, Recipe, FiringCurve)
        .outerjoin(User, Work.user_id == User.id)
        .outerjoin(Recipe, Work.recipe_id == Recipe.id)
        .outerjoin(FiringCurve, Work.curve_id == FiringCurve.id)
        .filter(Work.id == work_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="作品不存在")

    work, user, recipe, curve = row
    # 解析多图
    imgs = []
    if work.images:
        try:
            imgs = json.loads(work.images)
        except:
            imgs = []
    if not imgs and work.image:
        imgs = [work.image]
    favorite_count = db.query(Favorite).filter(Favorite.work_id == work.id).count()
    is_favorited = False
    if current_user_id > 0:
        is_favorited = db.query(Favorite).filter(
            Favorite.work_id == work.id,
            Favorite.user_id == current_user_id,
        ).first() is not None
    is_liked = False
    if current_user_id > 0:
        is_liked = db.query(Like).filter(
            Like.work_id == work.id,
            Like.user_id == current_user_id,
        ).first() is not None
    return {
        "id": work.id,
        "user_id": work.user_id,
        "nickname": user.nickname if user else f"用户{work.user_id}",
        "avatar": user.avatar if user else "",
        "recipe_id": work.recipe_id,
        "recipe_title": recipe.title if recipe else "",
        "recipe_cover": recipe.cover if recipe else "",
        "image": _image_url(work.image),
        "images": [_image_url(u) for u in imgs if u],
        "description": work.description or "",
        "body_material": work.body_material or "",
        "kiln_type": work.kiln_type or "",
        "kiln_type_other": work.kiln_type_other or "",
        "temperature": work.temperature or "",
        "created_at": work.created_at,
        "favorite_count": favorite_count,
        "is_favorited": is_favorited,
        "is_liked": is_liked,
        "likes": work.likes or 0,
        "glaze_colors": json.loads(work.glaze_colors) if work.glaze_colors else [],
        "surface": work.surface or "",
        "transparency": work.transparency or "",
        "curve_id": work.curve_id,
        "curve_name": curve.name if curve else "",
        "curve_data": {
            "name": curve.name,
            "type": curve.type,
            "target_temp": curve.target_temp,
            "segments": json.loads(curve.segments) if curve and curve.segments else [],
            "description": curve.description or "",
        } if curve else None,
    }
