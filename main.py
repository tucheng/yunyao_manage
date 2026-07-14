import json
import logging
from logging.handlers import TimedRotatingFileHandler
import os
import sys
import time

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

sys.path.insert(0, os.path.dirname(__file__))

from app_config import (
    ALLOW_DEV_CORS,
    CORS_ORIGINS,
    ADMIN_ALLOWED_IPS,
    IS_PRODUCTION,
    LOCAL_UPLOAD_DIR,
    LOG_DIR,
    LOG_LEVEL,
    LOG_TO_FILE,
    MAX_PAGE_SIZE,
)
from auth_utils import user_id_from_request
from image_utils import normalize_image_url, parse_image_list
from rate_limiter import RateLimiter
from routes import (
    admin,
    auth,
    complaints,
    curves,
    glossary,
    materials,
    notifications,
    ocr,
    recipe_ingredients,
    recipes,
    redeem,
    settings as settings_route,
    social,
    temperature_cones,
    upload,
    users,
    work_comments,
    works,
)

app = FastAPI(
    title="Yunyao App API",
    version="0.2.0",
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
)


@app.on_event("startup")
def startup_downgrade():
    """启动时补跑日切维护，并在每天 0 点刷新等级与额度。"""
    from database import SessionLocal
    from services.user_quota import ensure_system_levels, run_daily_maintenance

    # 启动时执行一次
    try:
        db = SessionLocal()
        ensure_system_levels(db)
        downgraded, refreshed = run_daily_maintenance(db)
        db.close()
        logger.info(f"[每日维护] 启动补跑完成：降级 {downgraded} 人，刷新额度 {refreshed} 人")
    except Exception as e:
        logger.error(f"[过期降级] 启动时执行失败: {e}")

    # 每晚 0 点执行
    import threading

    def _nightly_check():
        while True:
            now = time.localtime()
            tomorrow = time.struct_time((
                now.tm_year, now.tm_mon, now.tm_mday + 1,
                0, 0, 0, now.tm_wday, now.tm_yday, now.tm_isdst
            ))
            sleep_sec = time.mktime(tomorrow) - time.mktime(now)
            if sleep_sec < 0:
                sleep_sec += 86400
            time.sleep(sleep_sec)
            try:
                db = SessionLocal()
                downgraded, refreshed = run_daily_maintenance(db)
                db.close()
                logger.info(f"[每日维护] 降级 {downgraded} 人，刷新额度 {refreshed} 人")
            except Exception as e:
                logger.error(f"[过期降级] 定时执行失败: {e}")

    t = threading.Thread(target=_nightly_check, daemon=True)
    t.start()
    logger.info("[每日维护] 定时任务已启动，每晚 0:00 执行")


# ===== 日志配置：容器默认输出 stdout，本地可按天滚动文件 =====
log_handlers: list[logging.Handler] = [logging.StreamHandler()]
if LOG_TO_FILE:
    os.makedirs(LOG_DIR, exist_ok=True)
    log_handlers.append(TimedRotatingFileHandler(
        os.path.join(LOG_DIR, "server.log"),
        when="midnight",
        backupCount=14,
        encoding="utf-8",
    ))
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
    handlers=log_handlers,
    force=True,
)
logger = logging.getLogger("yunyao")
logger.info("=== 服务启动 ===")

_rate_limiter = RateLimiter()

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS or (["*"] if ALLOW_DEV_CORS else []),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-User-Id"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if IS_PRODUCTION:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    client_ip = request.client.host if request.client else "unknown"
    response = await call_next(request)
    cost = round((time.time() - start) * 1000)
    logger.info("%s %s %s %s %dms", request.method, request.url.path, client_ip, response.status_code, cost)
    return response


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    resp = _rate_limiter.check(request)
    if resp:
        return resp
    return await call_next(request)


@app.middleware("http")
async def admin_ip_whitelist(request: Request, call_next):
    if ADMIN_ALLOWED_IPS and request.url.path.startswith(("/admin", "/admin-panel")):
        client_ip = request.client.host if request.client else ""
        if client_ip not in ADMIN_ALLOWED_IPS:
            return Response(
                json.dumps({"detail": "无权访问"}, ensure_ascii=False),
                status_code=403,
                media_type="application/json",
            )
    return await call_next(request)


@app.middleware("http")
async def cap_page_size(request: Request, call_next):
    """限制列表接口单页最大数量"""
    ps = request.query_params.get("page_size")
    if ps:
        try:
            val = int(ps)
            if val > MAX_PAGE_SIZE:
                from starlette.datastructures import QueryParams
                params = dict(request.query_params)
                params["page_size"] = str(MAX_PAGE_SIZE)
                request.scope["query_string"] = str(QueryParams(params)).encode("ascii")
        except (ValueError, TypeError):
            pass
    return await call_next(request)


def _requires_auth(request: Request) -> bool:
    path = request.url.path
    method = request.method
    if path in ("/auth/login", "/auth/register", "/auth/send-code", "/auth/captcha", "/auth/find-user", "/auth/verify-code", "/auth/reset-password"):
        return False
    if path.startswith(("/admin", "/admin-panel", "/docs", "/openapi.json", "/uploads")):
        return False
    if path == "/users/publish-status":
        return bool(request.query_params.get("user_id"))
    if path == "/users/view-status":
        return True
    if path.startswith(('/materials', '/settings', '/users', '/social', '/notifications', '/complaints', '/upload', '/curves')):
        # curves: GET 查询公开
        if path.startswith('/curves') and method == 'GET':
            return False
        # materials: GET 列表公开（POST/PUT/DELETE 需登录）
        if path.startswith("/materials/body") and method == "GET":
            return False
        if path.startswith("/materials/catalog") and method == "GET":
            return False
        # substitutions 查询公开
        if path.endswith("/substitutions") and method == "GET":
            return False
        return True
    if path.startswith("/recipes"):
        public_get = method == "GET" and (
            path in ("/recipes", "/recipes/")
            or path.startswith(("/recipes/search", "/recipes/by-no/"))
            or path.count("/") == 2
        )
        return not public_get
    if path.startswith("/works"):
        public_get = method == "GET" and (
            path in ("/works", "/works/", "/works/search/config")
            or path.count("/") == 2
        )
        return not public_get
    return method not in ("GET", "HEAD", "OPTIONS")


@app.middleware("http")
async def require_signed_user_token(request: Request, call_next):
    if request.method == "OPTIONS" or not _requires_auth(request):
        return await call_next(request)

    try:
        token_user_id = user_id_from_request(request)
        if token_user_id is None:
            raise HTTPException(status_code=401, detail="Authentication required")

        claimed_ids: list[int] = []
        for key in ("user_id", "current_user_id"):
            if request.method == "GET" and request.url.path == "/users/profile" and key == "user_id":
                continue
            value = request.query_params.get(key)
            if value:
                claimed_ids.append(int(value))

        content_type = request.headers.get("content-type", "").lower()
        if request.method in ("POST", "PUT", "PATCH", "DELETE") and "application/json" in content_type:
            try:
                body = await request.json()
            except (json.JSONDecodeError, UnicodeDecodeError):
                body = None
            if isinstance(body, dict):
                for key in ("user_id", "current_user_id"):
                    value = body.get(key)
                    if value not in (None, "", 0, "0"):
                        claimed_ids.append(int(value))

        if any(claimed_id != token_user_id for claimed_id in claimed_ids):
            raise HTTPException(status_code=403, detail="User id does not match token")

        request.state.user_id = token_user_id
        return await call_next(request)
    except HTTPException as exc:
        return Response(
            json.dumps({"detail": exc.detail}, ensure_ascii=False),
            status_code=exc.status_code,
            media_type="application/json",
        )
    except ValueError:
        return Response(
            json.dumps({"detail": "Invalid user id"}, ensure_ascii=False),
            status_code=400,
            media_type="application/json",
        )


app.include_router(recipe_ingredients.router)
app.include_router(recipes.router)
app.include_router(redeem.router)
app.include_router(auth.router)
app.include_router(materials.router)
app.include_router(curves.router)
app.include_router(social.router)
app.include_router(works.router)
app.include_router(upload.router)
app.include_router(ocr.router)
app.include_router(work_comments.router)
app.include_router(glossary.router)
app.include_router(temperature_cones.router)
app.include_router(complaints.router)
app.include_router(notifications.router)
app.include_router(admin.router)
app.include_router(users.router)
app.include_router(settings_route.router)


class CachedStaticFiles(StaticFiles):
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def send_with_cache(message):
            if message["type"] == "http.response.start" and "headers" in message:
                headers = list(message["headers"])
                headers.append((b"cache-control", b"public, max-age=300"))
                message["headers"] = headers
            await send(message)

        await super().__call__(scope, receive, send_with_cache)


web_dir = os.path.join(os.path.dirname(__file__), "..", "yunyao_app", "dist", "build", "h5")
if os.path.exists(web_dir):
    app.mount("/web", CachedStaticFiles(directory=web_dir, html=True), name="web")

static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

uploads_dir = LOCAL_UPLOAD_DIR
os.makedirs(uploads_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")


# ===== 统一收藏列表（配方 + 作品）=====
from sqlalchemy.orm import Session
from database import get_db
from models import Favorite, Recipe, Work, User
from sqlalchemy import func


@app.get("/api/favorites")
def get_all_favorites(
    user_id: int,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    offset = (page - 1) * page_size

    # 配方收藏
    recipe_favs = (
        db.query(Favorite, Recipe, User)
        .join(Recipe, Favorite.recipe_id == Recipe.id)
        .join(User, Recipe.user_id == User.id)
        .filter(Favorite.user_id == user_id, Favorite.recipe_id.isnot(None))
        .order_by(Favorite.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )
    recipe_total = (
        db.query(func.count(Favorite.id))
        .filter(Favorite.user_id == user_id, Favorite.recipe_id.isnot(None))
        .scalar()
        or 0
    )

    # 作品收藏
    work_favs = (
        db.query(Favorite, Work, User)
        .join(Work, Favorite.work_id == Work.id)
        .join(User, Work.user_id == User.id)
        .filter(Favorite.user_id == user_id, Favorite.work_id.isnot(None))
        .order_by(Favorite.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )
    work_total = (
        db.query(func.count(Favorite.id))
        .filter(Favorite.user_id == user_id, Favorite.work_id.isnot(None))
        .scalar()
        or 0
    )

    # 合并排序（按收藏时间）
    items = []
    for fav, recipe, user in recipe_favs:
        items.append({
            "type": "recipe",
            "id": recipe.id,
            "title": recipe.title or "",
            "recipe_no": recipe.recipe_no or "",
            "author_name": user.nickname or user.username or "未知",
            "author_id": user.id,
            "cover": normalize_image_url(recipe.cover),
            "category": recipe.category or "",
            "favorited_at": fav.created_at.isoformat() if fav.created_at else "",
        })
    for fav, work, user in work_favs:
        items.append({
            "type": "work",
            "id": work.id,
            "title": work.description or "烧制作品",
            "author_name": user.nickname or user.username or "未知",
            "author_id": user.id,
            "cover": (parse_image_list(work.images) or [normalize_image_url(work.image)])[0],
            "category": work.body_material or "",
            "favorited_at": fav.created_at.isoformat() if fav.created_at else "",
        })

    # 按收藏时间排序
    items.sort(key=lambda x: x.get("favorited_at", ""), reverse=True)

    total = recipe_total + work_total
    return {
        "items": items[:page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": (offset + page_size) < total,
    }


@app.get("/")
def root():
    return {"status": "running"}


@app.get("/health/live", include_in_schema=False)
def health_live():
    return {"status": "ok"}


@app.get("/health/ready", include_in_schema=False)
def health_ready():
    from sqlalchemy import text
    from database import engine
    from storage import storage_healthcheck

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        storage_healthcheck()
    except Exception as exc:
        logger.error("readiness check failed: %s", exc)
        raise HTTPException(status_code=503, detail="service not ready") from exc
    return {"status": "ready"}


@app.get("/admin-panel")
def admin_panel():
    html_path = os.path.join(os.path.dirname(__file__), "static", "admin.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    return {"error": "admin page not found"}


@app.get("/admin")
@app.get("/admin/")
def admin_panel_alias():
    return admin_panel()
