import uuid
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Request
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from storage import save_object

router = APIRouter(prefix="/upload", tags=["上传"])

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


@router.post("/image")
async def upload_image(
    request: Request,
    file: UploadFile = File(...),
    kind: str = Form("misc"),
    db: Session = Depends(get_db),
):
    """上传图片，返回可直接访问的 URL"""
    get_current_user(request, db)
    # 验证文件扩展名
    import os
    ext = os.path.splitext(file.filename or "image.jpg")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式: {ext}，仅支持 {', '.join(ALLOWED_EXTENSIONS)}"
        )
    if file.content_type and file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="仅支持图片文件")

    # 读取文件内容
    content = await file.read()

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="文件太大，最大支持 10MB")
    if not _looks_like_image(content):
        raise HTTPException(status_code=400, detail="图片内容格式不正确")

    # 生成唯一文件名
    folder = {"recipe": "recipes", "work": "works"}.get((kind or "").strip().lower(), "misc")
    unique_name = f"{folder}/{uuid.uuid4().hex}{ext}"
    try:
        url = save_object(unique_name, content, file.content_type or "application/octet-stream")
    except Exception as exc:
        raise HTTPException(status_code=503, detail="文件存储暂不可用") from exc
    return {"url": url, "filename": unique_name, "kind": kind}


def _looks_like_image(content: bytes) -> bool:
    if content.startswith(b"\xff\xd8\xff"):
        return True
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if content.startswith((b"GIF87a", b"GIF89a")):
        return True
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return True
    return False
