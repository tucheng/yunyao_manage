"""兑换码：管理员生成、用户兑换使用期限"""
import random
import string
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from database import get_db
from models import User, RedeemCode, RedeemLog
from services.user_quota import MEMBER_LEVEL_ID, get_or_create_quota, reset_user_quota
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
from routes.admin import verify_admin
from auth_utils import user_id_from_request

router = APIRouter(prefix="/redeem", tags=["兑换码"])


def _generate_code(length=10) -> str:
    chars = string.ascii_uppercase + string.digits
    # 去掉易混淆字符
    chars = chars.replace("O", "").replace("0", "").replace("I", "").replace("L", "")
    return "".join(random.choices(chars, k=length))


# ========= 管理员接口 =========


class GenerateCodesBody(BaseModel):
    count: int = 1  # 生成数量
    days: int = 30  # 可兑换天数
    max_uses: int = 1  # 每个码最大使用次数


@router.post("/admin/generate")
def generate_codes(body: GenerateCodesBody, token: str = Query(...), db: Session = Depends(get_db)):
    """管理员批量生成兑换码"""
    verify_admin(token)

    if body.count < 1 or body.count > 100:
        raise HTTPException(status_code=400, detail="生成数量1-100")
    if body.days < 1:
        raise HTTPException(status_code=400, detail="天数必须大于0")

    codes = []
    for _ in range(body.count):
        code_str = _generate_code()
        # 防重复
        while db.query(RedeemCode).filter(RedeemCode.code == code_str).first():
            code_str = _generate_code()
        rc = RedeemCode(code=code_str, days=body.days, max_uses=body.max_uses)
        db.add(rc)
        codes.append(code_str)

    db.commit()
    return {"ok": True, "count": len(codes), "codes": codes}


@router.get("/admin/codes")
def list_codes(page: int = 1, page_size: int = Query(default=20, alias="page_size"),
               token: str = Query(...), db: Session = Depends(get_db)):
    """管理员查看兑换码列表"""
    verify_admin(token)

    qry = db.query(RedeemCode).order_by(RedeemCode.created_at.desc())
    total = qry.count()
    items = qry.offset((page - 1) * page_size).limit(page_size).all()

    # 查询每个兑换码的使用记录（用户信息）
    code_ids = [c.id for c in items]
    logs = db.query(RedeemLog).filter(RedeemLog.code_id.in_(code_ids)).all() if code_ids else []
    users_map = {}
    if logs:
        user_ids = set(l.user_id for l in logs)
        users_qry = db.query(User.id, User.username).filter(User.id.in_(user_ids)).all()
        for uid, uname in users_qry:
            users_map[uid] = uname
    # code_id -> [username, ...]
    used_by = {}
    logs_by_code = {}
    for log in logs:
        used_by.setdefault(log.code_id, []).append(users_map.get(log.user_id, f"id:{log.user_id}"))
        logs_by_code.setdefault(log.code_id, []).append({
            "user": users_map.get(log.user_id, f"id:{log.user_id}"),
            "before_expiry": str(log.before_expiry) if log.before_expiry else "",
            "after_expiry": str(log.after_expiry) if log.after_expiry else "",
            "days_added": log.days_added,
            "used_at": str(log.created_at) if log.created_at else "",
        })

    return {
        "items": [
            {
                "id": c.id,
                "code": c.code,
                "days": c.days,
                "max_uses": c.max_uses,
                "current_uses": c.current_uses,
                "is_active": bool(c.is_active),
                "created_at": str(c.created_at) if c.created_at else "",
                "used_by": used_by.get(c.id, []),
                "logs": logs_by_code.get(c.id, []),
            }
            for c in items
        ],
        "total": total,
        "unused_count": db.query(RedeemCode).filter(RedeemCode.current_uses == 0).count(),
        "page": page,
        "page_size": page_size,
    }


# ========= 用户接口 =========


class RedeemBody(BaseModel):
    code: str


@router.post("/use")
def redeem_code(body: RedeemBody, request: Request, db: Session = Depends(get_db)):
    """用户兑换使用期限"""
    user_id = user_id_from_request(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="请先登录")

    code_str = body.code.strip().upper()
    if not code_str:
        raise HTTPException(status_code=400, detail="请输入兑换码")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    rc = db.query(RedeemCode).filter(RedeemCode.code == code_str).with_for_update().first()
    if not rc:
        raise HTTPException(status_code=404, detail="兑换码不存在")
    if not rc.is_active:
        raise HTTPException(status_code=400, detail="兑换码已失效")
    if rc.current_uses >= rc.max_uses:
        raise HTTPException(status_code=400, detail="兑换码已用完")

    # 检查是否已兑过（每人每码限一次）
    existing = db.query(RedeemLog).filter(
        RedeemLog.code_id == rc.id, RedeemLog.user_id == user_id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="该兑换码你已经用过了")

    # 累加使用期限
    now = datetime.now()
    old_expires = user.expires_at
    base_time = old_expires if old_expires and old_expires > now else now
    new_expires = base_time + timedelta(days=rc.days)
    user.expires_at = new_expires
    user.level_id = MEMBER_LEVEL_ID

    # 记录
    rc.current_uses += 1
    log = RedeemLog(code_id=rc.id, user_id=user_id, days_added=rc.days,
                    before_expiry=old_expires, after_expiry=new_expires)
    db.add(log)
    quota = reset_user_quota(db, user)
    quota.redeem_count = (quota.redeem_count or 0) + 1
    db.commit()

    return {
        "ok": True,
        "days_added": rc.days,
        "expires_at": str(new_expires),
        "message": f"成功兑换 {rc.days} 天使用期限",
    }
