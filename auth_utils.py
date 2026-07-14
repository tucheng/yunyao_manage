import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app_config import ACCESS_TOKEN_EXPIRE_SECONDS, ADMIN_USER_IDS, AUTH_SECRET
from models import User

PBKDF2_ITERATIONS = 260_000


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("ascii"))


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    return "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ITERATIONS,
        _b64encode(salt),
        _b64encode(digest),
    )


def verify_password(password: str, stored_hash: str) -> tuple[bool, bool]:
    if not stored_hash:
        return False, False

    if stored_hash.startswith("pbkdf2_sha256$"):
        try:
            _, iterations, salt, digest = stored_hash.split("$", 3)
            actual = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                _b64decode(salt),
                int(iterations),
            )
            return hmac.compare_digest(_b64encode(actual), digest), False
        except Exception:
            return False, False

    legacy = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return hmac.compare_digest(legacy, stored_hash), True


def user_role(user: User) -> str:
    if user.is_admin:
        return "admin"
    return "admin" if user.id in ADMIN_USER_IDS else "user"


def create_access_token(user: User) -> str:
    now = int(time.time())
    payload = {
        "sub": str(user.id),
        "role": user_role(user),
        "iat": now,
        "exp": now + ACCESS_TOKEN_EXPIRE_SECONDS,
    }
    payload_raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b64 = _b64encode(payload_raw)
    sig = hmac.new(AUTH_SECRET.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).digest()
    return f"{payload_b64}.{_b64encode(sig)}"


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload_b64, sig_b64 = token.split(".", 1)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid token")

    expected = hmac.new(AUTH_SECRET.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).digest()
    if not hmac.compare_digest(_b64encode(expected), sig_b64):
        raise HTTPException(status_code=401, detail="Invalid token")

    try:
        payload = json.loads(_b64decode(payload_b64))
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    if int(payload.get("exp", 0)) < int(time.time()):
        raise HTTPException(status_code=401, detail="Token expired")
    return payload


def token_from_request(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return ""


def user_id_from_request(request: Request) -> int | None:
    token = token_from_request(request)
    if not token:
        return None
    payload = decode_access_token(token)
    try:
        return int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token")


def get_current_user(request: Request, db: Session) -> User:
    user_id = user_id_from_request(request)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def auth_payload(user: User) -> dict[str, Any]:
    return {
        "user_id": user.id,
        "username": user.username or "",
        "nickname": user.nickname or "",
        "role": user_role(user),
        "access_token": create_access_token(user),
        "token_type": "bearer",
    }
