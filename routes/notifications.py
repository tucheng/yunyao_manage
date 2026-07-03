from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import Notification, User
from pydantic import BaseModel
from datetime import datetime

router = APIRouter(prefix="/notifications", tags=["通知"])


class NotificationOut(BaseModel):
    id: int
    user_id: int
    from_user_id: int | None = None
    from_username: str = ""
    type: str
    work_id: int | None = None
    content: str = ""
    is_read: bool = False
    created_at: datetime | None = None

    class Config:
        from_attributes = True


class NotificationCreate(BaseModel):
    user_id: int
    from_user_id: int
    type: str
    work_id: int | None = None
    content: str = ""


# ----- 创建通知（供其他模块调用）-----
def add_notification(db: Session, user_id: int, from_user_id: int,
                     type: str, work_id: int = None, content: str = ""):
    """创建通知，跳过自己给自己发通知"""
    if user_id == from_user_id:
        return
    n = Notification(
        user_id=user_id,
        from_user_id=from_user_id,
        type=type,
        work_id=work_id,
        content=content,
    )
    db.add(n)
    db.commit()


# ----- 通知列表 -----
@router.get("/")
def list_notifications(
    user_id: int = Query(...),
    page: int = 1,
    page_size: int = Query(default=20, alias="page_size"),
    db: Session = Depends(get_db),
):
    notifications = (
        db.query(Notification)
        .filter(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # 查询用户名
    from_ids = {n.from_user_id for n in notifications if n.from_user_id}
    users = {}
    if from_ids:
        for u in db.query(User).filter(User.id.in_(from_ids)).all():
            users[u.id] = u.nickname or f"用户{u.id}"

    result = []
    for n in notifications:
        d = {
            "id": n.id,
            "user_id": n.user_id,
            "from_user_id": n.from_user_id,
            "from_username": users.get(n.from_user_id, "") if n.from_user_id else "",
            "type": n.type,
            "work_id": n.work_id,
            "content": n.content,
            "is_read": bool(n.is_read),
            "created_at": n.created_at,
        }
        result.append(d)

    total = db.query(Notification).filter(Notification.user_id == user_id).count()

    return {"results": result, "total": total, "page": page, "page_size": page_size}


# ----- 未读数 -----
@router.get("/unread_count")
def unread_count(user_id: int = Query(...), db: Session = Depends(get_db)):
    count = (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.is_read == False)
        .count()
    )
    return {"count": count}


# ----- 标记已读 -----
class MarkReadBody(BaseModel):
    user_id: int
    notification_id: int | None = None  # None = 全部标记已读


@router.post("/mark_read")
def mark_read(body: MarkReadBody, db: Session = Depends(get_db)):
    q = db.query(Notification).filter(Notification.user_id == body.user_id)
    if body.notification_id:
        q = q.filter(Notification.id == body.notification_id)
    q.update({"is_read": True})
    db.commit()
    return {"ok": True}
