from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import Complaint, User
from app_config import ADMIN_USER_IDS
from auth_utils import get_current_user

router = APIRouter(prefix="/complaints", tags=["投诉建议"])


class ComplaintCreate(BaseModel):
    user_id: int
    content: str
    images: str = ""


class ComplaintReply(BaseModel):
    reply: str


def _serialize(item: Complaint) -> dict:
    return {
        "id": item.id,
        "user_id": item.user_id,
        "content": item.content,
        "images": item.images or "",
        "status": item.status or "open",
        "reply": item.reply or "",
        "admin_id": item.admin_id,
        "created_at": item.created_at.isoformat() if item.created_at else "",
        "replied_at": item.replied_at.isoformat() if item.replied_at else "",
    }


@router.get("")
def list_complaints(
    user_id: int = Query(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    query = db.query(Complaint)
    if user.is_admin or user.id in ADMIN_USER_IDS:
        pass
    else:
        query = query.filter(Complaint.user_id == user_id)

    items = query.order_by(Complaint.created_at.desc()).all()
    return [_serialize(item) for item in items]


@router.post("")
def create_complaint(body: ComplaintCreate, db: Session = Depends(get_db)):
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="内容不能为空")

    user = db.query(User).filter(User.id == body.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    item = Complaint(
        user_id=body.user_id,
        content=content[:500],
        images=body.images or "",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return _serialize(item)


@router.post("/{complaint_id}/reply")
def reply_complaint(
    complaint_id: int,
    body: ComplaintReply,
    request: Request,
    db: Session = Depends(get_db),
):
    reply = (body.reply or "").strip()
    if not reply:
        raise HTTPException(status_code=400, detail="回复不能为空")

    item = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="反馈不存在")

    admin = get_current_user(request, db)
    if not admin.is_admin and admin.id not in ADMIN_USER_IDS:
        raise HTTPException(status_code=403, detail="无权回复反馈")

    item.reply = reply[:500]
    item.admin_id = admin.id
    item.status = "replied"
    item.replied_at = datetime.utcnow()
    db.commit()
    db.refresh(item)
    return _serialize(item)
