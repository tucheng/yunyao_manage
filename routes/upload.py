import asyncio
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from auth_utils import current_user, get_current_user
from database import get_db
from image_security import sanitize_image
from storage import save_object
from observability import UPLOADS

router = APIRouter(prefix="/upload", tags=["上传"], dependencies=[Depends(current_user)])
MAX_FILE_SIZE = 10 * 1024 * 1024


@router.post("/image")
async def upload_image(
    request: Request,
    file: UploadFile = File(...),
    kind: str = Form("misc"),
    db: Session = Depends(get_db),
):
    get_current_user(request, db)
    folder = {"recipe": "recipes", "work": "works"}.get((kind or "").strip().lower(), "misc")
    try:
        content, ext, content_type = await sanitize_image(
            file,
            max_bytes=MAX_FILE_SIZE,
            allowed_formats={"JPEG", "PNG", "GIF", "WEBP"},
            max_dimension=8192,
        )
        unique_name = f"{folder}/{uuid.uuid4().hex}{ext}"
        url = await asyncio.to_thread(save_object, unique_name, content, content_type)
        UPLOADS.labels(kind=folder, result="success").inc()
    except HTTPException:
        UPLOADS.labels(kind=folder, result="failure").inc()
        raise
    except Exception as exc:
        UPLOADS.labels(kind=folder, result="failure").inc()
        raise HTTPException(status_code=503, detail="文件存储暂不可用") from exc
    return {"url": url, "filename": unique_name, "kind": kind}
