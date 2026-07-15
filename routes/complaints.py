from datetime import datetime
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app_config import ADMIN_USER_IDS, S3_PUBLIC_BASE_URL
from auth_utils import current_user, get_current_user
from database import get_db
from models import Complaint, ComplaintReply as ComplaintReplyRecord, User
from image_utils import parse_image_list

router = APIRouter(prefix="/complaints", tags=["投诉建议"], dependencies=[Depends(current_user)])


def _sanitize_complaint_images(value: str) -> str:
    images = parse_image_list(value)
    if len(images) > 5:
        raise HTTPException(status_code=400, detail="最多上传5张图片")
    allowed = []
    s3_base = S3_PUBLIC_BASE_URL.rstrip("/")
    for image in images:
        parsed = urlsplit(image)
        is_local = not parsed.scheme and image.startswith(("/uploads/", "/media/"))
        is_s3 = bool(s3_base and image.startswith(s3_base + "/"))
        if not is_local and not is_s3:
            raise HTTPException(status_code=400, detail="投诉图片必须来自本站上传服务")
        allowed.append(image)
    return ",".join(allowed)


class ComplaintCreate(BaseModel):
    user_id: int
    content: str
    images: str = ""


class ComplaintReplyCreate(BaseModel):
    reply: str


class ComplaintResolvedUpdate(BaseModel):
    resolved: bool


def _is_admin(user: User) -> bool:
    return bool(user.is_admin or user.id in ADMIN_USER_IDS)


def serialize_complaint(item: Complaint, db: Session, include_user: bool = False) -> dict:
    reply_rows = (
        db.query(ComplaintReplyRecord, User)
        .join(User, User.id == ComplaintReplyRecord.admin_id)
        .filter(ComplaintReplyRecord.complaint_id == item.id)
        .order_by(ComplaintReplyRecord.created_at.asc(), ComplaintReplyRecord.id.asc())
        .all()
    )
    replies = [
        {
            "id": reply.id,
            "content": reply.content,
            "admin_id": reply.admin_id,
            "sender_name": admin.nickname or admin.username or "管理员",
            "created_at": reply.created_at.isoformat() if reply.created_at else "",
        }
        for reply, admin in reply_rows
    ]
    # Existing records stored one reply directly on complaints. Keep them visible
    # until every environment has been migrated to the conversation table.
    if item.reply and not replies:
        admin = db.query(User).filter(User.id == item.admin_id).first() if item.admin_id else None
        replies.append({
            "id": f"legacy-{item.id}",
            "content": item.reply,
            "admin_id": item.admin_id,
            "sender_name": (admin.nickname or admin.username) if admin else "管理员",
            "created_at": item.replied_at.isoformat() if item.replied_at else "",
        })

    result = {
        "id": item.id,
        "user_id": item.user_id,
        "content": item.content,
        "images": item.images or "",
        "status": item.status or "open",
        "reply": item.reply or "",
        "replies": replies,
        "is_answered": bool(replies),
        "is_resolved": bool(item.is_resolved),
        "resolved_at": item.resolved_at.isoformat() if item.resolved_at else "",
        "is_closed": bool(item.is_closed),
        "closed_at": item.closed_at.isoformat() if item.closed_at else "",
        "closed_by": item.closed_by,
        "admin_id": item.admin_id,
        "created_at": item.created_at.isoformat() if item.created_at else "",
        "replied_at": item.replied_at.isoformat() if item.replied_at else "",
    }
    if include_user:
        owner = db.query(User).filter(User.id == item.user_id).first()
        result["user"] = {
            "id": owner.id,
            "username": owner.username or "",
            "nickname": owner.nickname or "",
            "avatar": owner.avatar or "",
        } if owner else None
    return result


@router.get("")
def list_complaints(
    request: Request,
    user_id: int = Query(...),
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if current_user.id != user_id:
        raise HTTPException(status_code=403, detail="只能查看自己的反馈")
    items = (
        db.query(Complaint)
        .filter(Complaint.user_id == current_user.id)
        .order_by(Complaint.created_at.desc())
        .all()
    )
    return [serialize_complaint(item, db) for item in items]


@router.post("")
def create_complaint(body: ComplaintCreate, request: Request, db: Session = Depends(get_db)):
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="内容不能为空")
    current_user = get_current_user(request, db)
    if current_user.id != body.user_id:
        raise HTTPException(status_code=403, detail="不能替其他用户提交反馈")

    item = Complaint(
        user_id=current_user.id,
        content=content[:500],
        images=_sanitize_complaint_images(body.images),
        status="open",
        is_resolved=False,
        is_closed=False,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return serialize_complaint(item, db)


@router.put("/{complaint_id}/resolved")
def update_resolved_status(
    complaint_id: int,
    body: ComplaintResolvedUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    item = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="反馈不存在")
    if item.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="只能更新自己的反馈")

    item.is_resolved = body.resolved
    item.resolved_at = datetime.utcnow() if body.resolved else None
    item.status = "resolved" if body.resolved else ("replied" if item.reply else "open")
    db.commit()
    db.refresh(item)
    return serialize_complaint(item, db)


@router.post("/{complaint_id}/reply")
def reply_complaint(
    complaint_id: int,
    body: ComplaintReplyCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Backward-compatible admin reply endpoint; new admin UI uses /admin/complaints."""
    reply = (body.reply or "").strip()
    if not reply:
        raise HTTPException(status_code=400, detail="回复不能为空")
    admin = get_current_user(request, db)
    if not _is_admin(admin):
        raise HTTPException(status_code=403, detail="无权回复反馈")
    item = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="反馈不存在")

    db.add(ComplaintReplyRecord(complaint_id=item.id, admin_id=admin.id, content=reply[:1000]))
    item.reply = reply[:1000]
    item.admin_id = admin.id
    item.status = "resolved" if item.is_resolved else "replied"
    item.replied_at = datetime.utcnow()
    db.commit()
    db.refresh(item)
    return serialize_complaint(item, db)
