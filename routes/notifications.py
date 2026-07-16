from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from auth_utils import current_user
from models import Notification, User, UserSettings
from pydantic import BaseModel
from datetime import datetime
import json

router = APIRouter(prefix="/notifications", tags=["通知"], dependencies=[Depends(current_user)])

NOTIFICATION_TYPES = ("like", "favorite", "comment", "follow", "complaint_reply")
DEFAULT_PREFERENCES = {notification_type: True for notification_type in NOTIFICATION_TYPES}


class NotificationOut(BaseModel):
    id: int
    user_id: int
    from_user_id: int | None = None
    from_username: str = ""
    type: str
    work_id: int | None = None
    recipe_id: int | None = None
    complaint_id: int | None = None
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
    recipe_id: int | None = None
    complaint_id: int | None = None
    content: str = ""


class NotificationPreferencesUpdate(BaseModel):
    user_id: int
    preferences: dict[str, bool]


def get_notification_preferences(db: Session, user_id: int) -> dict[str, bool]:
    settings = db.query(UserSettings).filter(UserSettings.user_id == user_id).first()
    if not settings or not settings.notification_preferences:
        return DEFAULT_PREFERENCES.copy()
    try:
        saved = json.loads(settings.notification_preferences)
    except (TypeError, ValueError):
        saved = {}
    return {
        notification_type: bool(saved.get(notification_type, enabled))
        for notification_type, enabled in DEFAULT_PREFERENCES.items()
    }


# ----- 创建通知（供其他模块调用）-----
def add_notification(db: Session, user_id: int, from_user_id: int,
                     type: str, work_id: int = None, recipe_id: int = None,
                     complaint_id: int = None, content: str = ""):
    """创建通知，跳过自己给自己发通知"""
    if user_id == from_user_id:
        return
    if type in DEFAULT_PREFERENCES and not get_notification_preferences(db, user_id).get(type, True):
        return
    n = Notification(
        user_id=user_id,
        from_user_id=from_user_id,
        type=type,
        work_id=work_id,
        recipe_id=recipe_id,
        complaint_id=complaint_id,
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
            "recipe_id": n.recipe_id,
            "complaint_id": n.complaint_id,
            "content": n.content,
            "is_read": bool(n.is_read),
            "created_at": n.created_at,
        }
        result.append(d)

    total = db.query(Notification).filter(Notification.user_id == user_id).count()

    return {"results": result, "total": total, "page": page, "page_size": page_size}


@router.get("/preferences")
def read_preferences(user_id: int = Query(...), db: Session = Depends(get_db)):
    return {"preferences": get_notification_preferences(db, user_id)}


@router.put("/preferences")
def update_preferences(body: NotificationPreferencesUpdate, db: Session = Depends(get_db)):
    unknown_types = set(body.preferences) - set(NOTIFICATION_TYPES)
    if unknown_types:
        raise HTTPException(status_code=400, detail="包含不支持的提醒类型")

    preferences = get_notification_preferences(db, body.user_id)
    preferences.update({key: bool(value) for key, value in body.preferences.items()})
    settings = db.query(UserSettings).filter(UserSettings.user_id == body.user_id).first()
    if not settings:
        settings = UserSettings(user_id=body.user_id)
        db.add(settings)
    settings.notification_preferences = json.dumps(preferences, ensure_ascii=False)

    disabled_types = [key for key, enabled in preferences.items() if not enabled]
    if disabled_types:
        db.query(Notification).filter(
            Notification.user_id == body.user_id,
            Notification.type.in_(disabled_types),
            Notification.is_read == False,
        ).update({"is_read": True}, synchronize_session=False)
    db.commit()
    return {"preferences": preferences}


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
