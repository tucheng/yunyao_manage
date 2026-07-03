import io
import base64
import random
import re
import string
import time
import uuid

import requests
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app_config import ENABLE_MOCK_LOGIN, WX_APPID, WX_SECRET
from auth_utils import auth_payload, hash_password, verify_password, token_from_request, decode_access_token, user_role
from database import get_db
from models import User
from verification_sender import get_settings as get_verification_settings, send_verification_code

router = APIRouter(prefix="/auth", tags=["auth"])

CODE_TTL_SECONDS = 600
CAPTCHA_TTL = 300
_verification_codes: dict[str, tuple[str, float]] = {}
_captcha_codes: dict[str, tuple[str, float]] = {}


class NicknameUpdate(BaseModel):
    nickname: str


class RegisterRequest(BaseModel):
    email: str = ""
    phone: str = ""
    username: str = ""
    verification_code: str = ""
    captcha_id: str = ""
    captcha_code: str = ""
    password: str
    confirm_password: str = ""


class SendCodeRequest(BaseModel):
    email: str = ""
    phone: str = ""


class LoginRequest(BaseModel):
    code: str = ""
    email: str = ""
    phone: str = ""
    password: str = ""
    verification_code: str = ""
    username: str = ""


def _default_nickname(db: Session) -> str:
    return f"用户{db.query(User).count() + 1}"


def _normalize_verification_target(email: str, phone: str, db: Session) -> tuple[str, str, str]:
    email = email.strip().lower() if email else ""
    phone = phone.strip() if phone else ""
    if bool(email) == bool(phone):
        raise HTTPException(status_code=400, detail="请选择邮箱或手机号其中一种")
    if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(status_code=400, detail="邮箱格式不正确")
    if phone and not re.match(r"^1\d{10}$", phone):
        raise HTTPException(status_code=400, detail="手机号格式不正确")
    account_mode = get_verification_settings(db).get("verification_account_mode", "either")
    if account_mode == "sms" and email:
        raise HTTPException(status_code=400, detail="当前只允许手机号短信验证")
    if account_mode == "email" and phone:
        raise HTTPException(status_code=400, detail="当前只允许邮箱验证")
    return email, phone, f"email:{email}" if email else f"phone:{phone}"


def _verify_code(target_key: str, code: str) -> None:
    stored = _verification_codes.get(target_key)
    if not stored:
        raise HTTPException(status_code=400, detail="请先获取验证码")
    expected, expires_at = stored
    if expires_at < time.time():
        _verification_codes.pop(target_key, None)
        raise HTTPException(status_code=400, detail="验证码已过期")
    if code.strip() != expected:
        raise HTTPException(status_code=400, detail="验证码错误")
    _verification_codes.pop(target_key, None)


def _login_response(user: User, db: Session | None = None, password: str | None = None, upgrade_hash: bool = False):
    if db is not None and password and upgrade_hash:
        user.password_hash = hash_password(password)
        db.commit()
        db.refresh(user)
    return auth_payload(user)


@router.post("/send-code")
def send_code(body: SendCodeRequest, db: Session = Depends(get_db)):
    email, phone, target_key = _normalize_verification_target(body.email, body.phone, db)
    code = f"{random.randint(0, 999999):06d}"
    try:
        delivery = send_verification_code(db, email=email, phone=phone, code=code)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"验证码发送失败：{exc}")
    _verification_codes[target_key] = (code, time.time() + CODE_TTL_SECONDS)
    result = {
        "message": "验证码已发送",
        "target": email or phone,
        "expires_in": CODE_TTL_SECONDS,
        "channel": delivery.get("channel", "debug"),
    }
    if "debug_code" in delivery:
        result["debug_code"] = delivery["debug_code"]
    return result


@router.get("/captcha")
def get_captcha():
    code = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    captcha_id = uuid.uuid4().hex[:16]

    # 生成简单验证码图片
    width, height = 120, 40
    img = Image.new("RGB", (width, height), (245, 243, 240))
    draw = ImageDraw.Draw(img)
    for _ in range(4):
        x1 = random.randint(0, width)
        y1 = random.randint(0, height)
        x2 = random.randint(0, width)
        y2 = random.randint(0, height)
        draw.line([(x1, y1), (x2, y2)], fill=(200, 200, 200), width=1)
    font = ImageFont.load_default()
    for i, c in enumerate(code):
        x = 10 + i * 25
        y = 8 + random.randint(-6, 6)
        draw.text((x, y), c, fill=(80, 80, 80), font=font)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    _captcha_codes[captcha_id] = (code, time.time() + CAPTCHA_TTL)
    return {"captcha_id": captcha_id, "captcha_image": f"data:image/png;base64,{b64}"}


@router.get("/verify")
def verify_token(request: Request, db: Session = Depends(get_db)):
    """校验当前 token 是否有效"""
    token = token_from_request(request)
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")
    payload = decode_access_token(token)
    user = db.query(User).filter(User.id == int(payload["sub"])).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return {
        "valid": True,
        "user_id": user.id,
        "username": user.username or "",
        "nickname": user.nickname,
        "role": user_role(user),
    }


class FindUserRequest(BaseModel):
    username: str = ""
    email: str = ""


@router.post("/find-user")
def find_user(body: FindUserRequest, db: Session = Depends(get_db)):
    uname = body.username.strip()
    email = body.email.strip().lower() if body.email else ""
    if not uname or not email:
        raise HTTPException(status_code=400, detail="请填写用户名和邮箱")
    user = db.query(User).filter(
        User.username == uname, User.email == email
    ).first()
    if user:
        return {"found": True, "message": "已找到您的账号，请联系管理员重置密码"}
    return {"found": False, "message": "未找到匹配的用户名和邮箱"}


@router.post("/register")
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    email = body.email.strip() if body.email else ""
    phone = body.phone.strip() if body.phone else ""
    password = body.password

    if not email and not phone:
        raise HTTPException(status_code=400, detail="请填写邮箱或手机号")
    if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(status_code=400, detail="邮箱格式不正确")
    if phone and not re.match(r"^1\d{10}$", phone):
        raise HTTPException(status_code=400, detail="手机号格式不正确")

    if not password or len(password) < 6 or len(password) > 20:
        raise HTTPException(status_code=400, detail="密码6-20位")
    if password != body.confirm_password:
        raise HTTPException(status_code=400, detail="两次输入的密码不一致")

    # 图形验证码校验
    captcha_stored = _captcha_codes.get(body.captcha_id)
    if not captcha_stored:
        raise HTTPException(status_code=400, detail="请先获取图形验证码")
    expected_captcha, captcha_expires = captcha_stored
    if captcha_expires < time.time():
        _captcha_codes.pop(body.captcha_id, None)
        raise HTTPException(status_code=400, detail="图形验证码已过期")
    if body.captcha_code.strip().upper() != expected_captcha:
        raise HTTPException(status_code=400, detail="图形验证码错误")
    _captcha_codes.pop(body.captcha_id, None)

    if email and db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="该邮箱已注册")
    if phone and db.query(User).filter(User.phone == phone).first():
        raise HTTPException(status_code=400, detail="该手机号已注册")

    # 用户名处理
    username = body.username.strip() if body.username else ""
    if not username:
        raise HTTPException(status_code=400, detail="请输入用户名")
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=400, detail="该用户名已被使用")
    if db.query(User).filter(User.nickname == username).first():
        raise HTTPException(status_code=400, detail="该昵称已被使用")

    user = User(
        openid=f"email_{email}" if email else f"phone_{phone}",
        email=email or None,
        phone=phone or None,
        password_hash=hash_password(password),
        username=username,
        nickname=username,
        balance=10000,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return auth_payload(user)


@router.post("/login")
def login(body: LoginRequest, db: Session = Depends(get_db)):
    email = body.email.strip().lower() if body.email else ""
    phone = body.phone.strip() if body.phone else ""
    password = body.password
    verification_code = body.verification_code
    code = body.code

    if (email or phone) and verification_code:
        email, phone, target_key = _normalize_verification_target(email, phone, db)
        _verify_code(target_key, verification_code)
        if email:
            user = db.query(User).filter(User.email == email).first()
            if not user:
                raise HTTPException(status_code=404, detail="该邮箱未注册")
        else:
            user = db.query(User).filter(User.phone == phone).first()
            if not user:
                raise HTTPException(status_code=404, detail="该手机号未注册")
        return auth_payload(user)

    if email and password:
        user = db.query(User).filter(User.email == email).first()
        ok, upgrade_hash = verify_password(password, user.password_hash if user else "")
        if not user or not ok:
            raise HTTPException(status_code=401, detail="邮箱或密码错误")
        return _login_response(user, db, password, upgrade_hash)

    if phone and password:
        user = db.query(User).filter(User.phone == phone).first()
        ok, upgrade_hash = verify_password(password, user.password_hash if user else "")
        if not user or not ok:
            raise HTTPException(status_code=401, detail="手机号或密码错误")
        return _login_response(user, db, password, upgrade_hash)

    if body.username and password:
        # 支持用户名登录
        uname = body.username.strip()
        user = db.query(User).filter(
            (User.username == uname) | (User.email == uname) | (User.phone == uname)
        ).first()
        ok, upgrade_hash = verify_password(password, user.password_hash if user else "")
        if not user or not ok:
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        return _login_response(user, db, password, upgrade_hash)

    if code and ENABLE_MOCK_LOGIN and not WX_APPID:
        user = db.query(User).filter(User.openid == code).first()
        if not user:
            user = User(openid=code, nickname=_default_nickname(db), balance=10000)
            db.add(user)
            db.commit()
            db.refresh(user)
        return auth_payload(user)

    if code:
        if not WX_APPID or not WX_SECRET:
            raise HTTPException(status_code=500, detail="微信登录未配置")
        resp = requests.get(
            "https://api.weixin.qq.com/sns/jscode2session",
            params={
                "appid": WX_APPID,
                "secret": WX_SECRET,
                "js_code": code,
                "grant_type": "authorization_code",
            },
            timeout=8,
        )
        data = resp.json()
        if "openid" not in data:
            raise HTTPException(status_code=400, detail="登录失败")
        user = db.query(User).filter(User.openid == data["openid"]).first()
        if not user:
            user = User(openid=data["openid"], balance=0)
            db.add(user)
            db.commit()
            db.refresh(user)
        return auth_payload(user)

    raise HTTPException(status_code=400, detail="请提供登录方式")


@router.put("/nickname")
def update_nickname(body: NicknameUpdate, user_id: int = Query(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.nickname = body.nickname
    db.commit()
    return {"user_id": user.id, "nickname": user.nickname}


class ResetPasswordRequest(BaseModel):
    email: str
    verification_code: str
    password: str
    confirm_password: str = ""


@router.post("/reset-password")
def reset_password(body: ResetPasswordRequest, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(status_code=400, detail="邮箱格式不正确")

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="该邮箱未注册")

    if not body.password or len(body.password) < 6 or len(body.password) > 20:
        raise HTTPException(status_code=400, detail="密码6-20位")
    if body.password != body.confirm_password:
        raise HTTPException(status_code=400, detail="两次输入的密码不一致")

    _verify_code(f"email:{email}", body.verification_code)

    user.password_hash = hash_password(body.password)
    db.commit()
    return {"message": "密码重置成功"}


@router.post("/mp-login")
def mp_login(body: LoginRequest, db: Session = Depends(get_db)):
    return login(body, db)



