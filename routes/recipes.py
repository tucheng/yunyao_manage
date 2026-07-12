from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session, joinedload
from database import get_db
from models import Recipe, User, UserLevel, Purchase, Review, Favorite, Work, RecipeSequence, Like, RecipeView, RecipeIngredient, IngredientName, RecipeSeger, RecipeVersion
from schemas import (
    RecipeCreate, RecipeUpdate, RecipeOut, RecipeListItem,
    PurchaseCreate, PurchaseOut, ReviewCreate, ReviewOut,
)
from security import encrypt, decrypt, hash_for_lookup
from auth_utils import user_id_from_request
from sqlalchemy import text, func
from seger_calculator import calculate_seger
from services.recipe_version import snapshot_recipe
import json
import logging
from datetime import datetime

logger = logging.getLogger('yunyao')

router = APIRouter(prefix="/recipes", tags=["釉料配方"])


# ========= 唯一编号生成（行锁保证并发） =========

def generate_recipe_no(db: Session) -> str:
    """原子生成配方编号：A001→A999→B001→...→Z999→A0001→... 行锁防重"""
    seq = db.query(RecipeSequence).order_by(RecipeSequence.letter).with_for_update().first()
    if not seq:
        seq = RecipeSequence(letter="A", counter=0, digits=3)
        db.add(seq)
        db.flush()
    seq.counter += 1
    max_per_letter = 10 ** seq.digits - 1  # 3→999, 4→9999, 5→99999
    if seq.counter > max_per_letter:
        # 当前字母用完了，跳到下一个
        next_letter = chr(ord(seq.letter) + 1)
        if next_letter > "Z":
            # 所有字母用完，增加位数
            seq.digits += 1
            seq.letter = "A"
        else:
            seq.letter = next_letter
        seq.counter = 1
    db.flush()
    return f"{seq.letter}{seq.counter:0{seq.digits}d}"


@router.post("/init-sequence")
def init_recipe_sequence(db: Session = Depends(get_db)):
    """初始化编号计数器"""
    existing = db.query(RecipeSequence).first()
    if existing:
        return {"message": f"计数器已存在，当前：{existing.letter}{existing.counter:0{existing.digits}d}，位数：{existing.digits}"}
    db.add(RecipeSequence(letter="A", counter=0, digits=3))
    db.commit()
    return {"message": "已初始化，起始编号 A001"}


# ========= 列表 =========

def _public_recipe_query(db: Session):
    return db.query(Recipe).filter(
        Recipe.visibility.in_(["public", "paid", "showoff"])
    )


def _recipe_ingredient_names(recipe_id: int, db: Session) -> list[str]:
    """从 recipe_ingredients 表查原料名称（解密后返回）"""
    rows = db.query(RecipeIngredient.name).filter(
        RecipeIngredient.recipe_id == recipe_id
    ).all()
    return [decrypt(r[0]) for r in rows if r[0]]


def _recipe_has_material(recipe: Recipe, material: str, db: Session) -> bool:
    material = (material or "").strip()
    if not material:
        return True
    h = hash_for_lookup(material)
    return db.query(RecipeIngredient.id).filter(
        RecipeIngredient.recipe_id == recipe.id,
        RecipeIngredient.name_hash == h,
    ).first() is not None


def _recipe_has_all_materials(recipe: Recipe, materials_str: str, db: Session) -> bool:
    """AND 逻辑：配方必须包含所有指定的原料（哈希匹配）"""
    if not materials_str:
        return True
    materials = [m.strip() for m in materials_str.split(",") if m.strip()]
    if not materials:
        return True
    hashes = [hash_for_lookup(m) for m in materials]
    count = db.query(RecipeIngredient.id).filter(
        RecipeIngredient.recipe_id == recipe.id,
        RecipeIngredient.name_hash.in_(hashes),
    ).count()
    return count == len(hashes)


def _recipe_has_work(recipe: Recipe, work_count: int) -> bool:
    return bool(work_count and work_count > 0)


def _recipe_matches_search_filters(recipe: Recipe, material: str, has_work: str, work_count: int, materials: str = "", db: Session = None) -> bool:
    if material and not _recipe_has_material(recipe, material, db):
        return False
    if materials and not _recipe_has_all_materials(recipe, materials, db):
        return False
    has_linked_work = _recipe_has_work(recipe, work_count)
    if has_work == "yes" and not has_linked_work:
        return False
    if has_work == "no" and has_linked_work:
        return False
    return True


def _recipe_rows_with_work_counts(query):
    work_counts = (
        query.session.query(Work.recipe_id, func.count(Work.id).label("work_count"))
        .group_by(Work.recipe_id)
        .subquery()
    )
    # favorite count subquery
    fav_counts = (
        query.session.query(Favorite.recipe_id, func.count(Favorite.id).label("fav_count"))
        .filter(Favorite.recipe_id.isnot(None))
        .group_by(Favorite.recipe_id)
        .subquery()
    )
    # latest work per recipe via window function (works on MariaDB & MySQL)
    latest_work_subq = (
        query.session.query(
            Work.recipe_id,
            Work.image,
            Work.images,
            func.row_number().over(
                partition_by=Work.recipe_id,
                order_by=Work.created_at.desc()
            ).label("rn")
        )
        .subquery()
    )
    first_work = (
        query.session.query(
            latest_work_subq.c.recipe_id,
            latest_work_subq.c.image,
            latest_work_subq.c.images,
        )
        .filter(latest_work_subq.c.rn == 1)
        .subquery()
    )
    return (
        query.outerjoin(User, Recipe.user_id == User.id)
        .outerjoin(work_counts, Recipe.id == work_counts.c.recipe_id)
        .outerjoin(fav_counts, Recipe.id == fav_counts.c.recipe_id)
        .outerjoin(first_work, Recipe.id == first_work.c.recipe_id)
        .with_entities(Recipe, User.nickname, User.avatar, work_counts.c.work_count, first_work.c.image, first_work.c.images, fav_counts.c.fav_count)
    )


def _first_work_image(work_image: str, work_images_json: str) -> str:
    """从作品字段中提取第一张图片URL"""
    # 优先从 images JSON 数组取第一张
    if work_images_json and work_images_json != "[]":
        try:
            arr = json.loads(work_images_json)
            if arr and isinstance(arr, list) and arr[0]:
                return arr[0]
        except Exception:
            pass
    # fallback 到 image 主图
    return work_image or ""


def _serialize_recipe_list_item(recipe, nickname, avatar, work_count=0, work_image="", work_images="", favorite_count=0):
    setattr(recipe, 'author_name', nickname if nickname else f'用户{recipe.user_id}')
    setattr(recipe, 'avatar', avatar or "")
    setattr(recipe, 'work_count', work_count or 0)
    setattr(recipe, 'work_image', _first_work_image(work_image, work_images))
    setattr(recipe, 'favorite_count', favorite_count or 0)
    return recipe


@router.get("/search/config")
def recipe_search_config(db: Session = Depends(get_db)):
    # fallback 选项
    _KILN_OPTIONS = ["电窑", "气窑", "柴窑", "乐烧"]
    _SURFACE_OPTIONS = ["亮光", "丝光", "蜡光", "柔光", "无光", "磨砂"]
    _TRANSPARENCY_OPTIONS = ["高透", "微透", "半透", "不透"]

    # 原料 — 从 IngredientName 表取
    rows = db.query(IngredientName.name).order_by(IngredientName.name).all()
    material_names = [r[0] for r in rows]

    # 筛选项 — 从 Recipe 表取实际数据去重，确保能搜到结果
    _VISIBLE = ["public", "paid", "showoff"]
    kiln_types = [r[0] for r in db.query(Recipe.kiln_type).filter(
        Recipe.kiln_type != "", Recipe.kiln_type.isnot(None),
        Recipe.visibility.in_(_VISIBLE)
    ).distinct().order_by(Recipe.kiln_type).all()]
    surfaces = [r[0] for r in db.query(Recipe.surface).filter(
        Recipe.surface != "", Recipe.surface.isnot(None),
        Recipe.visibility.in_(_VISIBLE)
    ).distinct().order_by(Recipe.surface).all()]
    transparencies = [r[0] for r in db.query(Recipe.transparency).filter(
        Recipe.transparency != "", Recipe.transparency.isnot(None),
        Recipe.visibility.in_(_VISIBLE)
    ).distinct().order_by(Recipe.transparency).all()]

    # 温度和颜色 — 从 Recipe 表取实际值
    colors = [r[0] for r in db.query(Recipe.color).filter(Recipe.color != "", Recipe.color.isnot(None), Recipe.visibility.in_(_VISIBLE)).distinct().order_by(Recipe.color).all()]
    temperatures = [r[0] for r in db.query(Recipe.temperature).filter(Recipe.temperature != "", Recipe.temperature.isnot(None), Recipe.visibility.in_(_VISIBLE)).distinct().order_by(Recipe.temperature).all()]

    return {
        "materials": material_names,
        "kiln_types": kiln_types or _KILN_OPTIONS,
        "surfaces": surfaces or _SURFACE_OPTIONS,
        "transparencies": transparencies or _TRANSPARENCY_OPTIONS,
        "temperatures": temperatures,
        "colors": colors,
        "has_work_options": [
            {"value": "yes", "label": "有作品"},
            {"value": "no", "label": "无作品"},
        ],
    }


@router.get("/count")
def count_recipes(
    type: str = "",
    category: str = "",
    keyword: str = "",
    seller_id: int = 0,
    material: str = "",
    materials: str = "",
    has_work: str = "",
    surface: str = "",
    transparency: str = "",
    color: str = "",
    temperature: str = "",
    kiln_type: str = "",
    has_images: str = "",
    db: Session = Depends(get_db),
):
    query = _public_recipe_query(db)
    if type:
        query = query.filter(Recipe.type == type)
    if category:
        query = query.filter(Recipe.category == category)
    if seller_id > 0:
        query = query.filter(Recipe.user_id == seller_id)
    if keyword:
        query = query.filter(
            Recipe.title.contains(keyword)
        )
    if surface:
        query = query.filter(Recipe.surface == surface)
    if transparency:
        query = query.filter(Recipe.transparency == transparency)
    if color:
        query = query.filter(Recipe.color == color)
    if temperature:
        query = query.filter(Recipe.temperature == temperature)
    if kiln_type:
        query = query.filter(Recipe.kiln_type == kiln_type)
    if has_images == "1":
        query = query.filter(
            (Recipe.cover != "") | (Recipe.images.isnot(None)) | (Recipe.images != "[]")
        )
    elif has_images == "0":
        query = query.filter(
            (Recipe.cover == "") & ((Recipe.images.is_(None)) | (Recipe.images == "[]"))
        )
    rows_query = _recipe_rows_with_work_counts(query)
    if not material and not materials and not has_work:
        return {"count": query.count()}
    count = 0
    for recipe, _, _, work_count, *_ in rows_query.all():
        if _recipe_matches_search_filters(recipe, material, has_work, work_count or 0, materials, db):
            count += 1
    return {"count": count}


@router.get("/", response_model=list[RecipeListItem])
@router.get("", response_model=list[RecipeListItem], include_in_schema=False)
def list_recipes(
    type: str = "",
    category: str = "",
    keyword: str = "",
    seller_id: int = 0,
    material: str = "",
    materials: str = "",
    has_work: str = "",
    surface: str = "",
    transparency: str = "",
    color: str = "",
    temperature: str = "",
    kiln_type: str = "",
    has_images: str = "",  # "1"=有图 "0"=无图
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    """列出公开服务（配方/烧制/找配方）"""
    query = _public_recipe_query(db)

    if type:
        query = query.filter(Recipe.type == type)
    if category:
        query = query.filter(Recipe.category == category)
    if seller_id > 0:
        query = query.filter(Recipe.user_id == seller_id)
    if keyword:
        query = query.filter(
            Recipe.title.contains(keyword)
            | Recipe.recipe_no.contains(keyword)
        )
    if surface:
        query = query.filter(Recipe.surface == surface)
    if transparency:
        query = query.filter(Recipe.transparency == transparency)
    if color:
        query = query.filter(Recipe.color == color)
    if temperature:
        query = query.filter(Recipe.temperature == temperature)
    if kiln_type:
        query = query.filter(Recipe.kiln_type == kiln_type)
    if has_images == "1":
        query = query.filter(
            (Recipe.cover != "") | (Recipe.images.isnot(None)) | (Recipe.images != "[]")
        )
    elif has_images == "0":
        query = query.filter(
            (Recipe.cover == "") & ((Recipe.images.is_(None)) | (Recipe.images == "[]"))
        )

    rows_query = _recipe_rows_with_work_counts(query).order_by(Recipe.created_at.desc())
    if material or materials or has_work:
        filtered_rows = []
        for recipe, nickname, avatar, work_count, work_image, work_images, fav_count in rows_query.all():
            if _recipe_matches_search_filters(recipe, material, has_work, work_count or 0, materials, db):
                filtered_rows.append((recipe, nickname, avatar, work_count, work_image, work_images, fav_count))
        start = (page - 1) * page_size
        rows = filtered_rows[start:start + page_size]
    else:
        rows = (
            rows_query
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

    result = []
    for r, nickname, avatar, work_count, work_image, work_images, fav_count in rows:
        result.append(_serialize_recipe_list_item(r, nickname, avatar, work_count, work_image, work_images, fav_count))
    return result


# ========= 关注动态 =========

@router.get("/feed/following", response_model=list[RecipeListItem])
def following_recipes(
    user_id: int = Query(...),
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    """获取关注用户发布的配方"""
    from models import Follow
    # 找到关注列表
    following = db.query(Follow.followed_id).filter(
        Follow.follower_id == user_id
    ).all()
    followed_ids = [f.followed_id for f in following]
    if not followed_ids:
        return []

    query = db.query(Recipe).filter(
        Recipe.user_id.in_(followed_ids),
        Recipe.visibility.in_(["public", "paid", "showoff"]),
    )
    # favorite count subquery
    fav_counts = (
        db.query(Favorite.recipe_id, func.count(Favorite.id).label("fav_count"))
        .filter(Favorite.recipe_id.isnot(None))
        .group_by(Favorite.recipe_id)
        .subquery()
    )
    # latest work per recipe via window function
    subq = (
        db.query(
            Work.recipe_id,
            Work.image,
            Work.images,
            func.row_number().over(
                partition_by=Work.recipe_id,
                order_by=Work.created_at.desc()
            ).label("rn")
        )
        .subquery()
    )
    first_work = (
        db.query(
            subq.c.recipe_id,
            subq.c.image,
            subq.c.images,
        )
        .filter(subq.c.rn == 1)
        .subquery()
    )
    rows = (
        query.outerjoin(User, Recipe.user_id == User.id)
        .outerjoin(fav_counts, Recipe.id == fav_counts.c.recipe_id)
        .outerjoin(first_work, Recipe.id == first_work.c.recipe_id)
        .with_entities(Recipe, User.nickname, User.avatar, first_work.c.image, first_work.c.images, fav_counts.c.fav_count)
        .order_by(Recipe.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    result = []
    for r, nickname, avatar, work_img, work_imgs, fav_cnt in rows:
        setattr(r, 'author_name', nickname if nickname else f'用户{r.user_id}')
        setattr(r, 'avatar', avatar or "")
        setattr(r, 'work_image', _first_work_image(work_img or "", work_imgs or ""))
        setattr(r, 'favorite_count', fav_cnt or 0)
        result.append(r)
    return result


# ========= 我的 =========

@router.get("/mine", response_model=list[RecipeListItem])
def my_recipes(user_id: int = Query(...), db: Session = Depends(get_db)):
    recipes = (
        db.query(Recipe)
        .filter(Recipe.user_id == user_id)
        .order_by(Recipe.created_at.desc())
        .all()
    )
    mine = db.query(User).filter(User.id == user_id).first()
    myname = mine.nickname if mine else f"用户{user_id}"
    # 计算每个配方的收藏数
    recipe_ids = [r.id for r in recipes]
    fav_counts = (
        db.query(Favorite.recipe_id, func.count(Favorite.id).label("cnt"))
        .filter(Favorite.recipe_id.in_(recipe_ids))
        .group_by(Favorite.recipe_id)
        .all()
    )
    fav_map = {r.recipe_id: r.cnt for r in fav_counts}
    for r in recipes:
        setattr(r, 'author_name', myname)
        setattr(r, 'favorite_count', fav_map.get(r.id, 0))
    return recipes


# ========= 已购 =========

@router.get("/purchased", response_model=list[RecipeOut])
def purchased_recipes(user_id: int = Query(...), db: Session = Depends(get_db)):
    purchases = db.query(Purchase).filter(
        Purchase.buyer_id == user_id,
        Purchase.status.in_(["confirmed", "pending"]),
    ).all()
    recipe_ids = [p.recipe_id for p in purchases]
    recipes = db.query(Recipe).filter(Recipe.id.in_(recipe_ids)).all()
    return recipes


# ========= 收藏 =========

@router.post("/{recipe_id}/favorite")
def toggle_favorite(recipe_id: int, user_id: int = Query(...), db: Session = Depends(get_db)):
    existing = db.query(Favorite).filter(
        Favorite.recipe_id == recipe_id,
        Favorite.user_id == user_id,
    ).first()
    if existing:
        db.delete(existing)
        db.commit()
        return {"favorited": False}
    fav = Favorite(recipe_id=recipe_id, user_id=user_id)
    db.add(fav)
    db.commit()
    return {"favorited": True}


@router.post("/{recipe_id}/like")
def toggle_recipe_like(recipe_id: int, user_id: int = Query(...), db: Session = Depends(get_db)):
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="配方不存在")
    existing = db.query(Like).filter(
        Like.recipe_id == recipe_id,
        Like.user_id == user_id,
    ).first()
    if existing:
        db.delete(existing)
        recipe.likes = max(0, (recipe.likes or 1) - 1)
        db.commit()
        return {"liked": False, "likes": recipe.likes}
    like = Like(recipe_id=recipe_id, user_id=user_id)
    db.add(like)
    recipe.likes = (recipe.likes or 0) + 1
    db.commit()
    return {"liked": True, "likes": recipe.likes}


@router.post("/{recipe_id}/view")
def record_recipe_view(recipe_id: int, user_id: int = Query(...), db: Session = Depends(get_db)):
    """记录浏览；同一用户同一配方同一天只消耗一次额度。"""
    from services.user_quota import consume_recipe_view_once
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="配方不存在")
    if recipe.user_id == user_id:
        consumed, remaining = False, None
    else:
        consumed, remaining = consume_recipe_view_once(db, user, recipe_id)
    existing = db.query(RecipeView).filter(
        RecipeView.recipe_id == recipe_id,
        RecipeView.user_id == user_id,
    ).first()
    if not existing:
        db.add(RecipeView(recipe_id=recipe_id, user_id=user_id))
        db.commit()
    db.commit()
    return {"ok": True, "quota_consumed": consumed, "remaining": remaining}


@router.get("/favorites")
def favorite_recipes(
    user_id: int = Query(...),
    page: int = 1,
    page_size: int = Query(default=20, alias="page_size"),
    db: Session = Depends(get_db),
):
    # 先查总数
    total = db.query(Favorite).filter(Favorite.user_id == user_id).count()
    favs = (
        db.query(Favorite)
        .filter(Favorite.user_id == user_id)
        .order_by(Favorite.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    result = []
    for f in favs:
        if f.recipe_id:
            rid = f.recipe_id
            recipe = db.query(Recipe).filter(Recipe.id == rid).first()
            if recipe:
                user = db.query(User).filter(User.id == recipe.user_id).first()
                result.append({
                    "id": recipe.id,
                    "user_id": recipe.user_id,
                    "type": "recipe",
                    "title": recipe.title,
                    "recipe_no": recipe.recipe_no or '',
                    "category": recipe.category or '',
                    "cover": recipe.cover or (json.loads(recipe.images or '[]')[0] if recipe.images and recipe.images != '[]' else ''),
                    "author_name": user.nickname if user else '',
                    "price": recipe.price,
                    "created_at": recipe.created_at.isoformat() if recipe.created_at else '',
                })
        if f.work_id:
            wid = f.work_id
            work = db.query(Work).filter(Work.id == wid).first()
            if work:
                user = db.query(User).filter(User.id == work.user_id).first()
                result.append({
                    "id": work.id,
                    "user_id": work.user_id,
                    "type": "work",
                    "title": (work.description or '作品').split('\n')[0][:30],
                    "cover": work.image or '',
                    "author_name": user.nickname if user else '',
                    "body_material": work.body_material or '',
                    "created_at": work.created_at.isoformat() if work.created_at else '',
                })
    result.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return {
        "items": result,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ========= 用户信息（含信任分） =========

@router.get("/user/{user_id}")
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {
        "user_id": user.id,
        "nickname": user.nickname,
        "trust_score": user.trust_score or 100,
        "avatar": user.avatar,
    }


# ========= 搜索 =========

@router.get("/search")
def search(
    keyword: str = "",
    q: str = "",
    body_material: str = "",
    kiln_type: str = "",
    surface: str = "",
    transparency: str = "",
    color: str = "",
    temperature: str = "",
    has_images: str = "",  # "1"=有图 "0"=无图
    author_id: int = 0,
    user_id: int = 0,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    """搜索配方 + 带图的评价作品"""
    keyword = keyword or q
    import logging
    logger = logging.getLogger('yunyao')
    logger.info(f"SEARCH: keyword={repr(keyword)}, page={page}, page_size={page_size}")
    # 1. 搜索配方
    recipe_query = db.query(Recipe).filter(
        Recipe.visibility.in_(["public", "paid", "showoff"])
    )
    if keyword:
        recipe_query = recipe_query.filter(
            (Recipe.recipe_no == keyword) | (Recipe.title.contains(keyword))
        )
    if body_material:
        recipe_query = recipe_query.filter(Recipe.body_material == body_material)
    if kiln_type:
        recipe_query = recipe_query.filter(Recipe.kiln_type == kiln_type)
    if surface:
        recipe_query = recipe_query.filter(Recipe.surface == surface)
    if transparency:
        recipe_query = recipe_query.filter(Recipe.transparency == transparency)
    if color:
        recipe_query = recipe_query.filter(Recipe.color == color)
    if temperature:
        recipe_query = recipe_query.filter(Recipe.temperature == temperature)
    if has_images == "1":
        recipe_query = recipe_query.filter(
            (Recipe.cover != "") | (Recipe.images.isnot(None)) | (Recipe.images != "[]")
        )
    elif has_images == "0":
        recipe_query = recipe_query.filter(
            (Recipe.cover == "") & ((Recipe.images.is_(None)) | (Recipe.images == "[]"))
        )
    if author_id:
        recipe_query = recipe_query.filter(Recipe.user_id == author_id)

    recipes = (
        recipe_query.order_by(Recipe.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    recipe_list = []
    for r in recipes:
        user = db.query(User).filter(User.id == r.user_id).first()
        setattr(r, "author_name", user.nickname if user else f"用户{r.user_id}")
        setattr(r, "avatar", user.avatar if user else "")
        recipe_list.append(r)

    # 2. 搜索带图的评价（作品图）
    review_query = db.query(Review).filter(
        Review.image != "",
        Review.image.isnot(None),
        Review.parent_id.is_(None),
    )
    if keyword:
        review_query = review_query.filter(
            Review.content.contains(keyword)
        )
    if body_material:
        review_query = review_query.filter(Review.body_material == body_material)
    if kiln_type:
        review_query = review_query.filter(Review.kiln_type == kiln_type)

    reviews = (
        review_query.order_by(Review.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    review_list = []
    for r in reviews:
        user = db.query(User).filter(User.id == r.user_id).first()
        recipe = db.query(Recipe).filter(Recipe.id == r.recipe_id).first()
        review_list.append({
            "id": r.id,
            "recipe_id": r.recipe_id,
            "user_id": r.user_id,
            "image": r.image,
            "content": r.content or "",
            "body_material": r.body_material or "",
            "kiln_type": r.kiln_type or "",
            "temperature": r.temperature or "",
            "recipe_title": recipe.title if recipe else "",
            "nickname": user.nickname if user else f"用户{r.user_id}",
            "created_at": r.created_at,
        })

    return {
        "recipes": recipe_list,
        "works": review_list,
    }


# ========= 按编号查询 =========

@router.get("/by-no/{recipe_no}")
def get_recipe_by_no(recipe_no: str, db: Session = Depends(get_db)):
    recipe = db.query(Recipe).filter(Recipe.recipe_no == recipe_no).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="查不出此编号对应的配方")
    return recipe

# ========= 详情 =========

@router.get("/{recipe_id}", response_model=RecipeOut)
def get_recipe(
    recipe_id: int,
    request: Request,
    user_id: int = 0,
    db: Session = Depends(get_db),
):
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="不存在")
    current_user_id = user_id_from_request(request)
    if not current_user_id:
        raise HTTPException(status_code=401, detail="请先登录")

    # 私密配方：只有作者可看
    if recipe.visibility == "private" and recipe.user_id != current_user_id:
        raise HTTPException(status_code=404, detail="不存在")

    from services.user_quota import consume_recipe_view_once
    user = db.query(User).filter(User.id == current_user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    # 作者查看自己的配方不受每日额度限制，也不扣减查看额度。
    if recipe.user_id != current_user_id:
        consume_recipe_view_once(db, user, recipe_id)
        db.commit()

    # 付费/显摆模式：隐藏原料和步骤
    recipe.is_purchased = False
    if recipe.type == "recipe" and recipe.visibility in ("paid", "showoff") and recipe.user_id != current_user_id:
        if current_user_id > 0:
            purchase = db.query(Purchase).filter(
                Purchase.recipe_id == recipe_id,
                Purchase.buyer_id == current_user_id,
                Purchase.status == "confirmed",
            ).first()
            if purchase:
                recipe.is_purchased = True

    # 收藏状态
    recipe.is_favorited = False
    if current_user_id > 0:
        fav = db.query(Favorite).filter(
            Favorite.recipe_id == recipe_id,
            Favorite.user_id == current_user_id,
        ).first()
        if fav:
            recipe.is_favorited = True

    # 点赞状态
    recipe.is_liked = False
    if current_user_id > 0:
        liked = db.query(Like).filter(
            Like.recipe_id == recipe_id,
            Like.user_id == current_user_id,
        ).first()
        if liked:
            recipe.is_liked = True


    # 带上作者名和头像
    user = db.query(User).filter(User.id == recipe.user_id).first()
    recipe.author_name = user.nickname if user else f'用户{recipe.user_id}'
    recipe.avatar = user.avatar if user else ''

    # 平均评分
    avg = db.query(func.avg(Review.rating)).filter(
        Review.recipe_id == recipe_id,
        Review.parent_id.is_(None),
    ).scalar()
    recipe.rating_avg = round(float(avg), 1) if avg else 0

    # 收藏数
    recipe.favorite_count = db.query(Favorite).filter(
        Favorite.recipe_id == recipe_id,
    ).count()

    # 关联作品数
    recipe.works_count = db.query(Work).filter(
        Work.recipe_id == recipe_id,
    ).count()

    # 原料状态表（减少前端的额外查询）
    recipe.ingredient_statuses = {}
    if current_user_id > 0:
        from models import UserMaterial
        materials = db.query(UserMaterial).filter(
            UserMaterial.user_id == current_user_id,
        ).all()
        for m in materials:
            recipe.ingredient_statuses[m.name.strip().lower()] = m.status

    return recipe


# ========= Seger 辅助函数 =========


def _parse_seger_detail(detail_json: str) -> dict:
    """Parse seger_detail JSON and extract summary fields."""
    if not detail_json or detail_json == "{}":
        return {"unmatched": [], "skipped_additional": [], "found_no_oxides": [],
                "surface_prediction": {"surface": "", "note": ""},
                "firing_temp": {"cone": "", "temp_range": "", "note": ""},
                "thermal_expansion": {"na_k_ratio": 0, "details": []},
                "color_analysis": {"hints": []},
                "oxide_contributions": {}}
    try:
        detail = json.loads(detail_json)
        return {
            "unmatched": detail.get("unmatched", []),
            "skipped_additional": detail.get("skipped_additional", []),
            "found_no_oxides": detail.get("found_no_oxides", []),
            "surface_prediction": detail.get("surface_prediction", {"surface": "", "note": ""}),
            "firing_temp": detail.get("firing_temp", {"cone": "", "temp_range": "", "note": ""}),
            "thermal_expansion": detail.get("thermal_expansion", {"na_k_ratio": 0, "details": []}),
            "color_analysis": detail.get("color_analysis", {"hints": []}),
            "oxide_contributions": detail.get("oxide_contributions", {}),
        }
    except (json.JSONDecodeError, TypeError):
        return {"unmatched": [], "skipped_additional": [], "found_no_oxides": [],
                "surface_prediction": {"surface": "", "note": ""},
                "firing_temp": {"cone": "", "temp_range": "", "note": ""},
                "thermal_expansion": {"na_k_ratio": 0, "details": []},
                "color_analysis": {"hints": []},
                "oxide_contributions": {}}


@router.get("/{recipe_id}/seger")
def get_recipe_seger(recipe_id: int, db: Session = Depends(get_db)):
    """获取配方的 Seger 公式计算结果"""
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="配方不存在")

    seger = db.query(RecipeSeger).filter(RecipeSeger.recipe_id == recipe_id).first()
    if not seger:
        detail_info = {"unmatched": [], "skipped_additional": [], "found_no_oxides": []}
        return {
            "recipe_id": recipe_id,
            "seger_unified": "",
            "seger_al2o3": None,
            "seger_sio2": None,
            "seger_ro": None,
            "acid_base_ratio": None,
            "acid_base_note": "",
            "seger_detail": "{}",
            "calculated_at": None,
            **detail_info,
        }
    detail_info = _parse_seger_detail(seger.seger_detail)
    return {
        "recipe_id": seger.recipe_id,
        "seger_unified": seger.seger_unified,
        "seger_al2o3": seger.seger_al2o3,
        "seger_sio2": seger.seger_sio2,
        "seger_ro": seger.seger_ro,
        "acid_base_ratio": seger.acid_base_ratio,
        "acid_base_note": seger.acid_base_note,
        "seger_detail": seger.seger_detail,
        "calculated_at": seger.calculated_at.isoformat() if seger.calculated_at else None,
        **detail_info,
    }



# ========= 版本快照（snapshot_recipe 在 services/recipe_version.py） =========


# ========= 版本管理 =========

@router.get("/{recipe_id}/versions")
def list_recipe_versions(recipe_id: int, db: Session = Depends(get_db)):
    """获取配方历史版本列表"""
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="配方不存在")
    versions = db.query(RecipeVersion).filter(
        RecipeVersion.recipe_id == recipe_id
    ).order_by(RecipeVersion.version_no.desc()).all()
    return [{
        "id": v.id,
        "version_no": v.version_no,
        "note": v.note or "",
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "created_by": v.created_by,
    } for v in versions]


@router.get("/{recipe_id}/versions/{version_id}")
def get_recipe_version_detail(recipe_id: int, version_id: int, db: Session = Depends(get_db)):
    """获取某个版本的完整数据"""
    version = db.query(RecipeVersion).filter(
        RecipeVersion.id == version_id,
        RecipeVersion.recipe_id == recipe_id,
    ).first()
    if not version:
        raise HTTPException(status_code=404, detail="版本不存在")
    return {
        "id": version.id,
        "version_no": version.version_no,
        "note": version.note or "",
        "created_at": version.created_at.isoformat() if version.created_at else None,
        "recipe_data": json.loads(version.recipe_data),
        "ingredients_data": json.loads(version.ingredients_data),
        "seger_data": json.loads(version.seger_data) if version.seger_data else None,
    }


@router.post("/{recipe_id}/versions/{version_id}/restore")
def restore_recipe_version(
    recipe_id: int, version_id: int,
    user_id: int = Query(...),
    db: Session = Depends(get_db),
):
    """恢复到指定历史版本"""
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="配方不存在")
    if recipe.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权操作")

    # 先快照当前状态（防止恢复错了想回退）
    prev_version_no = db.query(RecipeVersion.version_no).filter(
        RecipeVersion.id == version_id, RecipeVersion.recipe_id == recipe_id
    ).scalar()
    snapshot_recipe(recipe_id, db, note=f"还原到 v{prev_version_no or '?'}", user_id=user_id)

    version = db.query(RecipeVersion).filter(
        RecipeVersion.id == version_id,
        RecipeVersion.recipe_id == recipe_id,
    ).first()
    if not version:
        raise HTTPException(status_code=404, detail="版本不存在")

    # 恢复 recipe 字段
    recipe_data = json.loads(version.recipe_data)
    for key, value in recipe_data.items():
        if hasattr(recipe, key) and key not in ("id", "user_id", "created_at", "recipe_no"):
            setattr(recipe, key, value)
    recipe.updated_at = func.now()
    db.flush()

    # 恢复 ingredients
    db.query(RecipeIngredient).filter(RecipeIngredient.recipe_id == recipe_id).delete()
    ing_list = json.loads(version.ingredients_data)
    for i, item in enumerate(ing_list):
        raw_name = (item.get("name") or "").strip()
        ing = RecipeIngredient(
            recipe_id=recipe_id,
            recipe_no=recipe.recipe_no or "",
            name=encrypt(raw_name),
            name_en=(item.get("name_en") or "").strip(),
            name_hash=hash_for_lookup(raw_name),
            amount=encrypt(str(item.get("amount") or "").strip()),
            unit=str(item.get("unit") or "").strip()[:20],
            note=item.get("note") or "",
            is_additional=1 if item.get("is_additional") else 0,
            sort_order=item.get("sort_order", i),
        )
        db.add(ing)
    db.commit()

    # 重新计算 Seger
    try:
        calculate_seger(recipe_id, db)
    except Exception as e:
        logger.error("Seger recalculation failed after restore recipe %s: %s", recipe_id, e)

    db.refresh(recipe)
    return recipe


# ========= 创建/更新/删除 =========

@router.post("/", response_model=RecipeOut)
def create_recipe(recipe: RecipeCreate, user_id: int = Query(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    from services.user_quota import consume_quota
    consume_quota(db, user, "paid_recipe" if (recipe.price or 0) > 0 else "free_recipe")

    # 处理釉色数据
    glaze_colors_json = "[]"
    if recipe.glaze_colors:
        # 支持 JSON 字符串或数组
        try:
            raw = json.loads(recipe.glaze_colors) if isinstance(recipe.glaze_colors, str) else recipe.glaze_colors
            if isinstance(raw, list):
                from color_names import get_glaze_colors_data
                hex_list = []
                for c in raw:
                    if isinstance(c, dict):
                        hex_list.append(c.get("hex", ""))
                    elif isinstance(c, str):
                        hex_list.append(c)
                    else:
                        hex_list.append(str(c))
                hex_list = [h for h in hex_list if h]
                colors_data = get_glaze_colors_data(hex_list) if hex_list else []
                glaze_colors_json = json.dumps(colors_data, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            glaze_colors_json = recipe.glaze_colors

    db_recipe = Recipe(
        user_id=user_id,
        title=recipe.title,
        recipe_no=generate_recipe_no(db),
        type=recipe.type,
        cover=recipe.cover,
        images=recipe.images,
        describe=recipe.describe,
        category=recipe.category,
        temperature=recipe.temperature,
        atmosphere=recipe.atmosphere,
        kiln_type=recipe.kiln_type,
        kiln_type_other=recipe.kiln_type_other,
        body_material=recipe.body_material,
        surface=recipe.surface,
        transparency=recipe.transparency,
        price=recipe.price,
        turnaround=recipe.turnaround,
        reward=recipe.reward,
        contact=recipe.contact,
        visibility=recipe.visibility,
        forked_from=recipe.forked_from,
        glaze_colors=glaze_colors_json,
    )
    db.add(db_recipe)
    db.commit()
    db.refresh(db_recipe)
    if recipe.work_id:
        work = db.query(Work).filter(Work.id == recipe.work_id).first()
        if work and work.user_id == user_id:
            work.recipe_id = db_recipe.id
            db.commit()
    # Trigger Seger formula calculation
    try:
        calculate_seger(db_recipe.id, db)
        logger.info("Seger calculation completed for recipe %s", db_recipe.id)
    except Exception as e:
        logger.error("Seger calculation failed for recipe %s: %s", db_recipe.id, e)
    return db_recipe


@router.put("/{recipe_id}", response_model=RecipeOut)
def update_recipe(
    recipe_id: int,
    recipe: RecipeUpdate,
    user_id: int = Query(...),
    db: Session = Depends(get_db),
):
    db_recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not db_recipe:
        raise HTTPException(status_code=404, detail="不存在")
    if db_recipe.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权修改")

    # 快照当前状态
    snapshot_recipe(recipe_id, db, note="编辑配方信息", user_id=user_id)

    update_data = recipe.model_dump(exclude_unset=True)
    if (db_recipe.price or 0) <= 0 and (update_data.get("price") or 0) > 0:
        from services.user_quota import consume_quota
        user = db.query(User).filter(User.id == user_id).first()
        consume_quota(db, user, "paid_recipe")

    # 处理釉色数据
    if "glaze_colors" in update_data and update_data["glaze_colors"]:
        gc = update_data["glaze_colors"]
        try:
            raw = json.loads(gc) if isinstance(gc, str) else gc
            if isinstance(raw, list):
                from color_names import get_glaze_colors_data
                hex_list = []
                for c in raw:
                    if isinstance(c, dict):
                        hex_list.append(c.get("hex", ""))
                    elif isinstance(c, str):
                        hex_list.append(c)
                    else:
                        hex_list.append(str(c))
                hex_list = [h for h in hex_list if h]
                colors_data = get_glaze_colors_data(hex_list) if hex_list else []
                update_data["glaze_colors"] = json.dumps(colors_data, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            pass  # keep original value
    for key, value in update_data.items():
        setattr(db_recipe, key, value)
    db_recipe.updated_at = func.now()
    db.commit()
    db.refresh(db_recipe)
    # Trigger Seger formula calculation
    try:
        calculate_seger(db_recipe.id, db)
        logger.info("Seger calculation completed for recipe %s", db_recipe.id)
    except Exception as e:
        logger.error("Seger calculation failed for recipe %s: %s", db_recipe.id, e)
    return db_recipe


@router.delete("/{recipe_id}")
def delete_recipe(recipe_id: int, user_id: int = Query(...), db: Session = Depends(get_db)):
    db_recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not db_recipe:
        raise HTTPException(status_code=404, detail="不存在")
    if db_recipe.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权删除")
    db.delete(db_recipe)
    db.commit()
    return {"message": "已删除"}


# ========= 购买 =========

@router.post("/buy", response_model=PurchaseOut)
def buy_recipe(body: PurchaseCreate, buyer_id: int = Query(...), db: Session = Depends(get_db)):
    recipe = db.query(Recipe).filter(Recipe.id == body.recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="不存在")
    if recipe.user_id == buyer_id:
        raise HTTPException(status_code=400, detail="不能购买自己的")

    existing = db.query(Purchase).filter(
        Purchase.recipe_id == body.recipe_id,
        Purchase.buyer_id == buyer_id,
        Purchase.status == "confirmed",
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="已购买过")

    amount = recipe.price or recipe.reward or 0
    if amount <= 0:
        raise HTTPException(status_code=400, detail="免费配方无需购买")

    buyer = db.query(User).filter(User.id == buyer_id).first()
    if not buyer or (buyer.balance or 0) < amount:
        raise HTTPException(status_code=400, detail=f"余额不足，需要 {amount} 币，当前 {(buyer.balance or 0)} 币")

    purchase = Purchase(
        recipe_id=body.recipe_id,
        buyer_id=buyer_id,
        seller_id=recipe.user_id,
        amount=amount,
        status="confirmed",
    )
    db.add(purchase)

    # 扣买家余额
    buyer.balance = (buyer.balance or 0) - amount

    # 加卖家余额
    seller = db.query(User).filter(User.id == recipe.user_id).first()
    seller.balance = (seller.balance or 0) + amount

    recipe.sold_count = (recipe.sold_count or 0) + 1
    db.commit()
    db.refresh(purchase)
    return purchase


# ========= 购买记录（用于评价） =========

@router.get("/{recipe_id}/purchase")
def get_purchase(recipe_id: int, user_id: int = Query(...), db: Session = Depends(get_db)):
    """查当前用户是否购买过此配方"""
    purchase = db.query(Purchase).filter(
        Purchase.recipe_id == recipe_id,
        Purchase.buyer_id == user_id,
        Purchase.status == "confirmed",
    ).first()
    if not purchase:
        # 没购买也查一下是否已评价（防止重复评价）
        review = db.query(Review).filter(
            Review.recipe_id == recipe_id,
            Review.user_id == user_id,
        ).first()
        return {
            "purchased": False,
            "reviewed": review is not None,
        }
    # 检查是否已评价
    review = db.query(Review).filter(
        Review.purchase_id == purchase.id,
    ).first()
    return {
        "purchased": True,
        "purchase_id": purchase.id,
        "reviewed": review is not None,
    }


# ========= 评价 =========

@router.post("/review")
def create_review(body: ReviewCreate, user_id: int = Query(...), db: Session = Depends(get_db)):
    # 如果绑定了购买记录，验证属于该用户
    if body.purchase_id:
        purchase = db.query(Purchase).filter(
            Purchase.id == body.purchase_id,
            Purchase.buyer_id == user_id,
        ).first()
        if not purchase:
            raise HTTPException(status_code=404, detail="购买记录不存在")

    # 如果是回复，验证父评论存在
    parent = None
    if body.parent_id:
        parent = db.query(Review).filter(Review.id == body.parent_id).first()
        if not parent:
            raise HTTPException(status_code=404, detail="回复的评论不存在")
        if parent.recipe_id != body.recipe_id:
            raise HTTPException(status_code=400, detail="不能回复其他配方的评论")

    review = Review(
        purchase_id=body.purchase_id if body.purchase_id > 0 else None,
        parent_id=body.parent_id if body.parent_id > 0 else None,
        recipe_id=body.recipe_id,
        user_id=user_id,
        rating=body.rating,
        content=body.content,
        image=body.image,
        body_material=body.body_material,
        kiln_type=body.kiln_type,
        kiln_type_other=body.kiln_type_other,
        temperature=body.temperature,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    user = db.query(User).filter(User.id == review.user_id).first()
    return {
        "id": review.id,
        "parent_id": review.parent_id,
        "user_id": review.user_id,
        "recipe_id": review.recipe_id,
        "rating": review.rating,
        "content": review.content or "",
        "image": review.image or "",
        "body_material": review.body_material or "",
        "kiln_type": review.kiln_type or "",
        "kiln_type_other": review.kiln_type_other or "",
        "temperature": review.temperature or "",
        "created_at": review.created_at,
        "nickname": user.nickname if user else f"用户{review.user_id}",
        "replies": [],
    }


@router.get("/{recipe_id}/reviews", response_model=list[ReviewOut])
def list_reviews(recipe_id: int, db: Session = Depends(get_db)):
    # 手动查所有回复，按 parent_id 分组
    all_replies = db.query(Review).filter(
        Review.recipe_id == recipe_id,
        Review.parent_id.isnot(None),
    ).all()
    reply_map = {}
    for reply in all_replies:
        pid = reply.parent_id
        if pid not in reply_map:
            reply_map[pid] = []
        reply_user = db.query(User).filter(User.id == reply.user_id).first()
        reply_map[pid].append({
            "id": reply.id,
            "parent_id": reply.parent_id,
            "user_id": reply.user_id,
            "recipe_id": reply.recipe_id,
            "rating": reply.rating,
            "content": reply.content or "",
            "image": reply.image or "",
            "body_material": reply.body_material or "",
            "kiln_type": reply.kiln_type or "",
            "kiln_type_other": reply.kiln_type_other or "",
            "temperature": reply.temperature or "",
            "created_at": reply.created_at,
            "nickname": reply_user.nickname if reply_user else f"用户{reply.user_id}",
            "replies": [],
        })

    # 只取顶级评论
    reviews = (
        db.query(Review)
        .filter(Review.recipe_id == recipe_id, Review.parent_id.is_(None))
        .order_by(Review.created_at.desc())
        .all()
    )

    result = []
    for r in reviews:
        user = db.query(User).filter(User.id == r.user_id).first()
        recipe = db.query(Recipe).filter(Recipe.id == r.recipe_id).first()
        result.append({
            "id": r.id,
            "parent_id": r.parent_id,
            "user_id": r.user_id,
            "recipe_id": r.recipe_id,
            "rating": r.rating,
            "content": r.content or "",
            "image": r.image or "",
            "body_material": r.body_material or "",
            "kiln_type": r.kiln_type or "",
            "kiln_type_other": r.kiln_type_other or "",
            "temperature": r.temperature or "",
            "created_at": r.created_at,
            "nickname": user.nickname if user else f"用户{r.user_id}",
            "recipe_title": recipe.title if recipe else "",
            "replies": reply_map.get(r.id, []),
        })

    return result
