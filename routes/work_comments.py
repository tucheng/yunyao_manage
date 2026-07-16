from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from database import get_db
from auth_utils import current_user
from models import User, Work, WorkComment
from schemas import WorkCommentCreate, WorkCommentOut
from routes.notifications import add_notification

router = APIRouter(prefix="/works", tags=["作品评论"])


def _ensure_comment_columns(db: Session):
    inspector = inspect(db.bind)
    if "work_comments" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("work_comments")}
        if "parent_id" not in cols:
            db.execute(text("ALTER TABLE work_comments ADD COLUMN parent_id INTEGER"))
            db.commit()


def _user_names(user_id: int, users: dict[int, User]) -> dict[str, str]:
    user = users.get(user_id)
    return {
        "username": (user.username or "") if user else "",
        "nickname": (user.nickname or "") if user else "",
    }


@router.get("/{work_id}/comments", response_model=list[WorkCommentOut])
def list_work_comments(work_id: int, db: Session = Depends(get_db)):
    _ensure_comment_columns(db)
    comments = (
        db.query(WorkComment)
        .filter(WorkComment.work_id == work_id)
        .order_by(WorkComment.created_at.asc())
        .all()
    )
    user_ids = [c.user_id for c in comments] or [0]
    users = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()}

    reply_map: dict[int, list[WorkComment]] = {}
    for comment in comments:
        if comment.parent_id:
            reply_map.setdefault(comment.parent_id, []).append(comment)

    result = []
    for comment in comments:
        if comment.parent_id:
            continue
        replies = []
        for reply in reply_map.get(comment.id, []):
            replies.append({
                "id": reply.id,
                "parent_id": reply.parent_id,
                "work_id": reply.work_id,
                "user_id": reply.user_id,
                "content": reply.content,
                "created_at": reply.created_at,
                **_user_names(reply.user_id, users),
                "replies": [],
            })
        result.append({
            "id": comment.id,
            "parent_id": comment.parent_id,
            "work_id": comment.work_id,
            "user_id": comment.user_id,
            "content": comment.content,
            "created_at": comment.created_at,
            **_user_names(comment.user_id, users),
            "replies": replies,
        })
    return result


@router.post("/{work_id}/comments", response_model=WorkCommentOut, dependencies=[Depends(current_user)])
def create_work_comment(work_id: int, body: WorkCommentCreate, db: Session = Depends(get_db)):
    _ensure_comment_columns(db)
    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="评论内容不能为空")
    if not body.user_id:
        raise HTTPException(status_code=400, detail="请先登录")

    parent_id = body.parent_id if body.parent_id and body.parent_id > 0 else None
    parent = None
    if parent_id:
        parent = db.query(WorkComment).filter(
            WorkComment.id == parent_id,
            WorkComment.work_id == work_id,
        ).first()
        if not parent:
            raise HTTPException(status_code=404, detail="回复的评论不存在")

    comment = WorkComment(
        work_id=work_id,
        parent_id=parent_id,
        user_id=body.user_id,
        content=content,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    user = db.query(User).filter(User.id == body.user_id).first()

    # 回复优先通知被回复者，顶级评论通知作品主人。
    work = db.query(Work).filter(Work.id == work_id).first()
    target_user_id = parent.user_id if parent else (work.user_id if work else None)
    if target_user_id and target_user_id != body.user_id:
        username = (user.nickname or user.username) if user else f"用户{body.user_id}"
        add_notification(
            db=db,
            user_id=target_user_id,
            from_user_id=body.user_id,
            type="comment",
            work_id=work_id,
            content=f"{username} {'回复了你的评论' if parent else '评论了你的作品'}",
        )

    return {
        "id": comment.id,
        "parent_id": comment.parent_id,
        "work_id": comment.work_id,
        "user_id": comment.user_id,
        "content": comment.content,
        "created_at": comment.created_at,
        "username": (user.username or "") if user else "",
        "nickname": (user.nickname or "") if user else "",
        "replies": [],
    }
