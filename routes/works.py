from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from database import get_db
from models import Work, Recipe, User, Favorite, WorkComment, FiringCurve, Like
from sqlalchemy import func
import json
from color_names import get_glaze_colors_data
from image_utils import normalize_image_url, serialize_image_list
from auth_utils import current_user, user_id_from_request
from services.work_images import sanitize_work_images as _sanitize_work_images
from services.work_recipe import (
    recipe_for_work_link as _recipe_for_work_link,
    set_work_recipe as _set_work_recipe,
)
from services.work_search import (
    HAS_RECIPE_OPTIONS,
    distinct_work_values as _distinct_work_values,
    get_color_ranges as _get_color_ranges,
    get_temperature_ranges as _get_temperature_ranges,
    work_matches_search_filters as _work_matches_search_filters,
)
from routes.notifications import add_notification

router = APIRouter(prefix="/works", tags=["作品"])




# ---------- 关注动态 ----------


@router.get("/feed/following", dependencies=[Depends(current_user)])
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
        primary_image, images = _sanitize_work_images(work.image, work.images)
        result.append({
            "id": work.id,
            "user_id": work.user_id,
            "nickname": user.nickname if user else f"用户{work.user_id}",
            "avatar": user.avatar if user else "",
            "recipe_id": work.recipe_id,
            "image": primary_image,
            "images": images,
            "description": work.description or "",
            "category": work.category or "",
            "atmosphere": work.atmosphere or "",
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


    return (durable[0] if durable else ""), durable


# 初始化表





@router.get("/search/config")
def get_work_search_config(db: Session = Depends(get_db)):
    """作品高级搜索配置。"""
    return {
        "categories": _distinct_work_values(db, Work.category),
        "atmospheres": _distinct_work_values(db, Work.atmosphere),
        "body_materials": _distinct_work_values(db, Work.body_material),
        "kiln_types": _distinct_work_values(db, Work.kiln_type),
        "temperatures": _distinct_work_values(db, Work.temperature),
        "temperature_ranges": _get_temperature_ranges(db),
        "surfaces": _distinct_work_values(db, Work.surface),
        "transparencies": _distinct_work_values(db, Work.transparency),
        "color_ranges": _get_color_ranges(db),
        "has_recipe_options": HAS_RECIPE_OPTIONS,
    }


@router.get("/count")
def count_works(
    recipe_id: int = 0,
    user_id: int = 0,
    q: str = "",
    category: str = "",
    atmosphere: str = "",
    body_material: str = "",
    kiln_type: str = "",
    temperature: str = "",
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
            | Work.category.like(like)
            | Work.atmosphere.like(like)
            | Work.body_material.like(like)
            | Work.kiln_type.like(like)
            | Work.temperature.like(like)
            | Work.surface.like(like)
            | Work.transparency.like(like)
            | User.nickname.like(like)
        )

    has_search_filters = any([
        category,
        atmosphere,
        body_material,
        kiln_type,
        temperature,
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
            category,
            atmosphere,
            body_material,
            kiln_type,
            temperature,
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
    category: str = "",
    atmosphere: str = "",
    body_material: str = "",
    kiln_type: str = "",
    temperature: str = "",
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
            | Work.category.like(like)
            | Work.atmosphere.like(like)
            | Work.body_material.like(like)
            | Work.kiln_type.like(like)
            | Work.temperature.like(like)
            | Work.surface.like(like)
            | Work.transparency.like(like)
            | User.nickname.like(like)
        )
    ordered_query = query.order_by(Work.created_at.desc())
    has_search_filters = any([
        category,
        atmosphere,
        body_material,
        kiln_type,
        temperature,
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
                category,
                atmosphere,
                body_material,
                kiln_type,
                temperature,
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
        image, imgs = _sanitize_work_images(work.image, work.images)
        result.append({
            "id": work.id,
            "user_id": work.user_id,
            "nickname": user.nickname if user else f"用户{work.user_id}",
            "avatar": user.avatar if user else "",
            "recipe_id": work.recipe_id,
            "recipe_title": recipe.title if recipe else "",
            "image": image,
            "images": imgs,
            "description": work.description or "",
            "category": work.category or "",
            "atmosphere": work.atmosphere or "",
            "body_material": work.body_material or "",
            "kiln_type": work.kiln_type or "",
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


@router.put("/{work_id}", dependencies=[Depends(current_user)])
def update_work(work_id: int, data: dict, db: Session = Depends(get_db)):
    """更新作品"""
    work = db.query(Work).filter(Work.id == work_id).first()
    if not work:
        raise HTTPException(status_code=404, detail="作品不存在")

    user_id = data.get("user_id", 0)
    if not user_id or work.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权编辑")

    image, images_raw = _sanitize_work_images(data.get("image"), data.get("images"))
    if not image:
        raise HTTPException(status_code=400, detail="作品图片不能为空或为无效临时地址")
    description = data.get("description", "")
    category = data.get("category", "")
    atmosphere = data.get("atmosphere", "")
    body_material = data.get("body_material", "")
    kiln_type = data.get("kiln_type", "")
    temperature = data.get("temperature", "")
    surface = data.get("surface", "")
    transparency = data.get("transparency", "")
    curve_id = data.get("curve_id") or None
    if curve_id and not db.query(FiringCurve).filter(FiringCurve.id == curve_id, FiringCurve.user_id == user_id).first():
        raise HTTPException(status_code=400, detail="烧制曲线不存在或不属于当前用户")

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
    work.images = serialize_image_list(images_raw)
    work.description = description
    work.category = category
    work.atmosphere = atmosphere
    work.body_material = body_material
    work.kiln_type = kiln_type
    work.temperature = temperature
    work.surface = surface
    work.transparency = transparency
    work.curve_id = curve_id
    work.glaze_colors = glaze_colors_json
    if "recipe_id" in data:
        _set_work_recipe(db, work, data.get("recipe_id"), user_id)

    db.commit()
    db.refresh(work)
    return {"id": work.id, "message": "更新成功"}


@router.post("/", dependencies=[Depends(current_user)])
def create_work(
    data: dict,
    db: Session = Depends(get_db),
):
    """发布作品"""
    image, images_raw = _sanitize_work_images(data.get("image"), data.get("images"))
    user_id = data.get("user_id", 0)
    description = data.get("description", "")
    category = data.get("category", "")
    atmosphere = data.get("atmosphere", "")
    body_material = data.get("body_material", "")
    kiln_type = data.get("kiln_type", "")
    temperature = data.get("temperature", "")
    surface = data.get("surface", "")
    transparency = data.get("transparency", "")
    curve_id = data.get("curve_id") or None
    
    if not image:
        raise HTTPException(status_code=400, detail="作品图片不能为空或为无效临时地址")
    
    if not user_id:
        raise HTTPException(status_code=400, detail="用户未登录")

    if curve_id and not db.query(FiringCurve).filter(FiringCurve.id == curve_id, FiringCurve.user_id == user_id).first():
        raise HTTPException(status_code=400, detail="烧制曲线不存在或不属于当前用户")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    from services.user_quota import consume_quota
    consume_quota(db, user, "work")
    linked_recipe = _recipe_for_work_link(db, data.get("recipe_id"), user_id)

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
        recipe_id=linked_recipe.id if linked_recipe else None,
        image=image,
        images=serialize_image_list(images_raw),
        description=description,
        category=category,
        atmosphere=atmosphere,
        body_material=body_material,
        kiln_type=kiln_type,
        temperature=temperature,
        surface=surface,
        transparency=transparency,
        curve_id=curve_id,
        glaze_colors=glaze_colors_json,
    )
    db.add(work)
    if linked_recipe:
        linked_recipe.work_count = (linked_recipe.work_count or 0) + 1
    db.commit()
    db.refresh(work)
    return {"id": work.id, "message": "发布成功"}


@router.post("/{work_id}/favorite", dependencies=[Depends(current_user)])
def toggle_work_favorite(work_id: int, data: dict, db: Session = Depends(get_db)):
    """收藏/取消收藏作品"""
    user_id = data.get("user_id", 0)
    if not user_id:
        raise HTTPException(status_code=400, detail="请先登录")
    work = db.query(Work).filter(Work.id == work_id).first()
    if not work:
        raise HTTPException(status_code=404, detail="作品不存在")
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
    actor = db.query(User).filter(User.id == user_id).first()
    actor_name = (actor.nickname or actor.username) if actor else f"用户{user_id}"
    add_notification(
        db, user_id=work.user_id, from_user_id=user_id, type="favorite",
        work_id=work_id, content=f"{actor_name} 收藏了你的作品",
    )
    return {"favorited": True, "favorite_count": db.query(Favorite).filter(Favorite.work_id == work_id).count()}


@router.post("/{work_id}/like", dependencies=[Depends(current_user)])
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
    actor = db.query(User).filter(User.id == user_id).first()
    actor_name = (actor.nickname or actor.username) if actor else f"用户{user_id}"
    add_notification(
        db, user_id=work.user_id, from_user_id=user_id, type="like",
        work_id=work_id, content=f"{actor_name} 点赞了你的作品",
    )
    return {"liked": True, "likes": work.likes}


@router.post("/{work_id}/link_recipe", dependencies=[Depends(current_user)])
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
    _set_work_recipe(db, work, recipe_id, user_id)
    db.commit()
    return {"message": "已关联配方", "work_id": work.id, "recipe_id": recipe_id}


@router.get("/{work_id}")
def get_work(work_id: int, request: Request, current_user_id: int = 0, db: Session = Depends(get_db)):
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
    current_user_id = user_id_from_request(request) or 0
    can_expose_recipe = bool(
        recipe and (recipe.visibility in ("public", "showoff") or recipe.user_id == current_user_id)
    )
    image, imgs = _sanitize_work_images(work.image, work.images)
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
        "recipe_id": work.recipe_id if can_expose_recipe else None,
        "recipe_title": recipe.title if can_expose_recipe else "",
        "recipe_cover": normalize_image_url(recipe.cover) if can_expose_recipe else "",
        "image": image,
        "images": imgs,
        "description": work.description or "",
        "category": work.category or "",
        "atmosphere": work.atmosphere or "",
        "body_material": work.body_material or "",
        "kiln_type": work.kiln_type or "",
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
