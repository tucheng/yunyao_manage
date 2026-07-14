import io
import base64
import random
import re
import string
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth_utils import auth_payload, hash_password, verify_password, token_from_request, decode_access_token, user_role
from database import get_db
from encryption_utils import encrypt, hash_for_lookup
from models import User
from routes.curves import create_default_user_curves
from services.user_quota import get_or_create_quota
from verification_sender import get_settings as get_verification_settings, send_verification_code
from datetime import datetime, timedelta

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
    email: str = ""
    phone: str = ""
    password: str = ""
    verification_code: str = ""
    username: str = ""


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


def _verify_code(target_key: str, code: str, consume: bool = True) -> None:
    stored = _verification_codes.get(target_key)
    if not stored:
        raise HTTPException(status_code=400, detail="请先获取验证码")
    expected, expires_at = stored
    if expires_at < time.time():
        _verification_codes.pop(target_key, None)
        raise HTTPException(status_code=400, detail="验证码已过期")
    if code.strip() != expected:
        raise HTTPException(status_code=400, detail="验证码错误")
    if consume:
        _verification_codes.pop(target_key, None)


def _login_response(user: User, db: Session | None = None, password: str | None = None, upgrade_hash: bool = False):
    if db is not None and password and upgrade_hash:
        user.password = hash_password(password)
        db.commit()
        db.refresh(user)
    return auth_payload(user)


def _initialize_new_user(db: Session, user: User) -> None:
    """注册成功后立即按当前等级生成当天额度。"""
    get_or_create_quota(db, user)
    db.commit()


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
    user = User.by_email(db, email)
    if user and user.username == uname:
        return {"found": True, "message": "已找到您的账号"}
    return {"found": False, "message": "未找到匹配的用户名和邮箱"}


class VerifyCodeRequest(BaseModel):
    email: str = ""
    phone: str = ""
    code: str


@router.post("/verify-code")
def verify_code(body: VerifyCodeRequest, db: Session = Depends(get_db)):
    email, phone, target_key = _normalize_verification_target(body.email, body.phone, db)
    stored = _verification_codes.get(target_key)
    if not stored:
        raise HTTPException(status_code=400, detail="请先获取验证码")
    expected, expires_at = stored
    if expires_at < time.time():
        _verification_codes.pop(target_key, None)
        raise HTTPException(status_code=400, detail="验证码已过期")
    if body.code.strip() != expected:
        raise HTTPException(status_code=400, detail="验证码错误")
    # 不删除验证码，让 reset-password 接口消费
    return {"valid": True, "message": "验证码正确"}


@router.post("/register")
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    # ===== 第一步：格式校验 =====
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

    # 用户名格式：必填、2-20位
    username = body.username.strip() if body.username else ""
    if not username:
        raise HTTPException(status_code=400, detail="请输入用户名")
    if len(username) < 2 or len(username) > 20:
        raise HTTPException(status_code=400, detail="用户名2-20个字符")
    if not re.match(r"^[a-zA-Z0-9_\u4e00-\u9fff]+$", username):
        raise HTTPException(status_code=400, detail="用户名只能包含中英文、数字和下划线")

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

    # ===== 第二步：唯一性校验 =====
    if email and User.by_email(db, email):
        raise HTTPException(status_code=400, detail="该邮箱已注册")
    if phone and User.by_phone(db, phone):
        raise HTTPException(status_code=400, detail="该手机号已注册")
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=400, detail="该用户名已被使用")

    enc_email = encrypt(email) if email else None
    enc_phone = encrypt(phone) if phone else None
    user = User(
        email=enc_email,
        phone=enc_phone,
        email_hash=hash_for_lookup(email) if email else None,
        phone_hash=hash_for_lookup(phone) if phone else None,
        password=hash_password(password),
        username=username,
        nickname=username,
        level_id=1,
        expires_at=datetime.now() + timedelta(days=3),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    _initialize_new_user(db, user)
    create_default_user_curves(db, user.id)
    return auth_payload(user)


@router.post("/login")
def login(body: LoginRequest, db: Session = Depends(get_db)):
    email = body.email.strip().lower() if body.email else ""
    phone = body.phone.strip() if body.phone else ""
    password = body.password
    verification_code = body.verification_code

    if (email or phone) and verification_code:
        email, phone, target_key = _normalize_verification_target(email, phone, db)
        _verify_code(target_key, verification_code)
        if email:
            user = User.by_email(db, email)
            if not user:
                raise HTTPException(status_code=404, detail="该邮箱未注册")
        else:
            user = User.by_phone(db, phone)
            if not user:
                raise HTTPException(status_code=404, detail="该手机号未注册")
        return auth_payload(user)

    if email and password:
        user = User.by_email(db, email)
        ok, upgrade_hash = verify_password(password, user.password if user else "")
        if not user or not ok:
            raise HTTPException(status_code=401, detail="邮箱或密码错误")
        return _login_response(user, db, password, upgrade_hash)

    if phone and password:
        user = User.by_phone(db, phone)
        ok, upgrade_hash = verify_password(password, user.password if user else "")
        if not user or not ok:
            raise HTTPException(status_code=401, detail="手机号或密码错误")
        return _login_response(user, db, password, upgrade_hash)

    if body.username and password:
        uname = body.username.strip()
        user = db.query(User).filter(User.username == uname).first()
        if not user:
            user = User.by_email_or_phone(db, uname)
        ok, upgrade_hash = verify_password(password, user.password if user else "")
        if not user or not ok:
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        return _login_response(user, db, password, upgrade_hash)

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

    user = User.by_email(db, email)
    if not user:
        raise HTTPException(status_code=404, detail="该邮箱未注册")

    if not body.password or len(body.password) < 6 or len(body.password) > 20:
        raise HTTPException(status_code=400, detail="密码6-20位")
    if body.password != body.confirm_password:
        raise HTTPException(status_code=400, detail="两次输入的密码不一致")

    _verify_code(f"email:{email}", body.verification_code)

    user.password = hash_password(body.password)
    db.commit()
    return {"message": "密码重置成功"}
