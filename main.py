import json
import logging
from logging.handlers import TimedRotatingFileHandler
import os
import re
import sys
import time
import uuid

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.exc import IntegrityError
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Receive, Scope, Send
from prometheus_client import make_asgi_app

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
from rate_limiter import RateLimiter
from database import engine
from observability import (
    HTTP_DURATION,
    HTTP_REQUESTS,
    configure_json_logging,
    init_error_tracking,
    instrument_sql,
    request_id_var,
)
from services.business_errors import QuotaExceeded
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


@app.exception_handler(QuotaExceeded)
async def quota_exceeded_handler(_request: Request, exc: QuotaExceeded):
    """Return an expected business response that existing clients can display."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.detail,
            "code": exc.code,
            "quota_kind": exc.quota_kind,
            "remaining": exc.remaining,
        },
    )


@app.exception_handler(IntegrityError)
async def database_conflict_handler(_request: Request, _exc: IntegrityError):
    return JSONResponse(status_code=409, content={"detail": "数据冲突，请刷新后重试"})


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
configure_json_logging(LOG_LEVEL, log_handlers)
init_error_tracking()
instrument_sql(engine)
logger = logging.getLogger("yunyao")
logger.info("=== 服务启动 ===")

_rate_limiter = RateLimiter()

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS or (["*"] if ALLOW_DEV_CORS else []),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.url.path.startswith(("/admin", "/static/admin/")):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data: http: https:; "
            "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        )
    if IS_PRODUCTION:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    incoming_request_id = request.headers.get("x-request-id", "").strip()
    request_id = (
        incoming_request_id[:128]
        if incoming_request_id and re.fullmatch(r"[A-Za-z0-9._-]{1,128}", incoming_request_id)
        else uuid.uuid4().hex
    )
    token = request_id_var.set(request_id)
    request.state.request_id = request_id
    client_ip = request.client.host if request.client else "unknown"
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception:
        logger.exception("unhandled_request_error", extra={"method": request.method, "path": request.url.path})
        raise
    finally:
        elapsed = time.perf_counter() - start
        route = request.scope.get("route")
        route_label = getattr(route, "path", "unmatched")
        HTTP_REQUESTS.labels(request.method, route_label, str(status)).inc()
        HTTP_DURATION.labels(request.method, route_label).observe(elapsed)
        logger.info(
            "request_complete",
            extra={
                "method": request.method, "path": request.url.path, "client_ip": client_ip,
                "status": status, "duration_ms": round(elapsed * 1000, 2),
            },
        )
        request_id_var.reset(token)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    resp = await _rate_limiter.check(request)
    if resp:
        return resp
    return await call_next(request)


@app.on_event("shutdown")
async def close_shared_clients():
    await _rate_limiter.close()


@app.middleware("http")
async def admin_ip_whitelist(request: Request, call_next):
    if ADMIN_ALLOWED_IPS and request.url.path.startswith(("/admin", "/admin-panel")):
        client_ip = _rate_limiter.client_ip(request)
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
app.mount("/metrics", make_asgi_app())


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


@app.get("/")
def root():
    return {"status": "running"}


@app.get("/health/live", include_in_schema=False)
def health_live():
    return {"status": "ok"}


@app.get("/health/ready", include_in_schema=False)
async def health_ready():
    from sqlalchemy import text
    from database import engine
    from storage import storage_healthcheck

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        storage_healthcheck()
        await _rate_limiter.healthcheck()
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
