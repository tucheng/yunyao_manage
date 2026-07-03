from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, func, desc
from database import get_db
from models import User, Follow, Message
from routes.notifications import add_notification

router = APIRouter(prefix="/social", tags=["社交"])


# ========= 关注/取关 =========


@router.post("/follow/{target_id}")
def follow_user(target_id: int, user_id: int = Query(...), db: Session = Depends(get_db)):
    """关注用户"""
    if user_id == target_id:
        raise HTTPException(status_code=400, detail="不能关注自己")

    target = db.query(User).filter(User.id == target_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")

    existing = db.query(Follow).filter(
        Follow.follower_id == user_id,
        Follow.followed_id == target_id,
    ).first()
    if existing:
        return {"message": "已关注", "is_following": True}

    follow = Follow(follower_id=user_id, followed_id=target_id)
    db.add(follow)
    db.commit()

    # 给被关注者发通知
    me = db.query(User).filter(User.id == user_id).first()
    myname = me.nickname if me else f"用户{user_id}"
    add_notification(
        db=db,
        user_id=target_id,
        from_user_id=user_id,
        type="follow",
        content=f"{myname} 关注了你",
    )

    return {"message": "关注成功", "is_following": True}


@router.delete("/follow/{target_id}")
def unfollow_user(target_id: int, user_id: int = Query(...), db: Session = Depends(get_db)):
    """取消关注"""
    existing = db.query(Follow).filter(
        Follow.follower_id == user_id,
        Follow.followed_id == target_id,
    ).first()
    if not existing:
        raise HTTPException(status_code=404, detail="尚未关注")

    db.delete(existing)
    db.commit()
    return {"message": "已取消关注", "is_following": False}


@router.get("/following")
def list_following(user_id: int = Query(...), db: Session = Depends(get_db)):
    """我关注的人"""
    follows = db.query(Follow).filter(Follow.follower_id == user_id).all()
    followed_ids = [f.followed_id for f in follows]

    if not followed_ids:
        return []

    users = db.query(User).filter(User.id.in_(followed_ids)).all()
    user_map = {u.id: u for u in users}

    # 查出哪些人关注了我（用于 is_mutual）
    follower_set = set()
    my_followers = db.query(Follow).filter(Follow.followed_id == user_id).all()
    for f in my_followers:
        follower_set.add(f.follower_id)

    result = []
    for f in follows:
        u = user_map.get(f.followed_id)
        result.append({
            "id": f.followed_id,
            "nickname": u.nickname if u else f"用户{f.followed_id}",
            "avatar": u.avatar if u else "",
            "is_mutual": f.followed_id in follower_set,
            "created_at": f.created_at,
        })
    return result


@router.get("/followers")
def list_followers(user_id: int = Query(...), db: Session = Depends(get_db)):
    """我的粉丝"""
    follows = db.query(Follow).filter(Follow.followed_id == user_id).all()
    follower_ids = [f.follower_id for f in follows]

    if not follower_ids:
        return []

    users = db.query(User).filter(User.id.in_(follower_ids)).all()
    user_map = {u.id: u for u in users}

    # 查出我关注了哪些人（用于 is_mutual）
    following_set = set()
    my_following = db.query(Follow).filter(Follow.follower_id == user_id).all()
    for f in my_following:
        following_set.add(f.followed_id)

    result = []
    for f in follows:
        u = user_map.get(f.follower_id)
        result.append({
            "id": f.follower_id,
            "nickname": u.nickname if u else f"用户{f.follower_id}",
            "avatar": u.avatar if u else "",
            "is_mutual": f.follower_id in following_set,
            "created_at": f.created_at,
        })
    return result


@router.get("/status")
def follow_status(target_id: int = Query(...), user_id: int = Query(...), db: Session = Depends(get_db)):
    """查看与某个用户的关注关系"""
    is_following = db.query(Follow).filter(
        Follow.follower_id == user_id,
        Follow.followed_id == target_id,
    ).first() is not None

    is_follower = db.query(Follow).filter(
        Follow.follower_id == target_id,
        Follow.followed_id == user_id,
    ).first() is not None

    return {
        "is_following": is_following,
        "is_follower": is_follower,
        "is_mutual": is_following and is_follower,
    }


# ========= 私信 =========


@router.get("/conversations")
def list_conversations(user_id: int = Query(...), db: Session = Depends(get_db)):
    """获取会话列表，每个会话包含最后一条消息和未读数"""
    # 找出所有和我有过消息往来的用户
    sent = db.query(Message.receiver_id).filter(Message.sender_id == user_id).distinct().subquery()
    received = db.query(Message.sender_id).filter(Message.receiver_id == user_id).distinct().subquery()

    # 取并集
    from sqlalchemy import union
    all_ids = db.query(sent.c.receiver_id.label("uid")).union(
        db.query(received.c.sender_id.label("uid"))
    ).subquery()

    # 如果没有会话，返回空列表
    count = db.query(all_ids).count()
    if count == 0:
        return []

    # 对每个会话对方，查最后一条消息和未读数
    other_ids = [row.uid for row in db.query(all_ids).all()]
    users = db.query(User).filter(User.id.in_(other_ids)).all()
    user_map = {u.id: u for u in users}

    result = []
    for other_id in other_ids:
        # 最后一条消息（两人之间的所有消息）
        last_msg = (
            db.query(Message)
            .filter(
                or_(
                    and_(Message.sender_id == user_id, Message.receiver_id == other_id),
                    and_(Message.sender_id == other_id, Message.receiver_id == user_id),
                )
            )
            .order_by(Message.created_at.desc())
            .first()
        )

        # 未读消息数（对方发给我的未读）
        unread_count = db.query(Message).filter(
            Message.sender_id == other_id,
            Message.receiver_id == user_id,
            Message.is_read == False,
        ).count()

        u = user_map.get(other_id)
        result.append({
            "other_user_id": other_id,
            "nickname": u.nickname if u else f"用户{other_id}",
            "avatar": u.avatar if u else "",
            "last_message": last_msg.content if last_msg else "",
            "last_time": last_msg.created_at if last_msg else None,
            "unread_count": unread_count,
        })

    # 按最后消息时间倒序排列
    result.sort(key=lambda x: x["last_time"] or "", reverse=True)
    return result


@router.get("/messages/{other_user_id}")
def get_messages(
    other_user_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user_id: int = Query(...),
    db: Session = Depends(get_db),
):
    """获取与某个用户的聊天记录，按时间倒序分页"""
    messages = (
        db.query(Message)
        .filter(
            or_(
                and_(Message.sender_id == user_id, Message.receiver_id == other_user_id),
                and_(Message.sender_id == other_user_id, Message.receiver_id == user_id),
            )
        )
        .order_by(Message.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    if not messages:
        return []

    # 获取发送者和接收者的昵称
    user_ids = set()
    for m in messages:
        user_ids.add(m.sender_id)
        user_ids.add(m.receiver_id)
    users = db.query(User).filter(User.id.in_(user_ids)).all()
    user_map = {u.id: u for u in users}

    result = []
    for m in messages:
        sender = user_map.get(m.sender_id)
        receiver = user_map.get(m.receiver_id)
        result.append({
            "id": m.id,
            "sender_id": m.sender_id,
            "receiver_id": m.receiver_id,
            "sender_nickname": sender.nickname if sender else f"用户{m.sender_id}",
            "receiver_nickname": receiver.nickname if receiver else f"用户{m.receiver_id}",
            "content": m.content,
            "recipe_id": m.recipe_id,
            "is_read": m.is_read,
            "created_at": m.created_at,
        })

    return result


@router.post("/messages/{other_user_id}")
def send_message(
    other_user_id: int,
    body: dict,
    user_id: int = Query(...),
    db: Session = Depends(get_db),
):
    """发送消息"""
    if user_id == other_user_id:
        raise HTTPException(status_code=400, detail="不能给自己发消息")

    target = db.query(User).filter(User.id == other_user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="对方用户不存在")

    content = body.get("content", "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="消息内容不能为空")

    recipe_id = body.get("recipe_id")

    msg = Message(
        sender_id=user_id,
        receiver_id=other_user_id,
        content=content,
        recipe_id=recipe_id,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    sender = db.query(User).filter(User.id == user_id).first()
    return {
        "id": msg.id,
        "sender_id": msg.sender_id,
        "receiver_id": msg.receiver_id,
        "sender_nickname": sender.nickname if sender else f"用户{user_id}",
        "content": msg.content,
        "recipe_id": msg.recipe_id,
        "created_at": msg.created_at,
        "is_read": False,
    }


@router.post("/messages/{message_id}/read")
def mark_as_read(message_id: int, user_id: int = Query(...), db: Session = Depends(get_db)):
    """标记消息为已读"""
    msg = db.query(Message).filter(Message.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="消息不存在")

    # 只能标记自己收到的消息
    if msg.receiver_id != user_id:
        raise HTTPException(status_code=403, detail="无权操作")

    msg.is_read = True
    db.commit()
    return {"message": "已标记为已读"}


@router.get("/unread-count")
def unread_count(user_id: int = Query(...), db: Session = Depends(get_db)):
    """获取总未读消息数"""
    count = db.query(Message).filter(
        Message.receiver_id == user_id,
        Message.is_read == False,
    ).count()
    return {"unread_count": count}
