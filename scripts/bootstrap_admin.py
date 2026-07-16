"""Create or promote the first administrator from mounted secrets."""

import os
import re

from database import SessionLocal
from auth_utils import hash_password
from models import User
from services.user_quota import NORMAL_LEVEL_ID, ensure_system_levels


def _read_required(name: str) -> str:
    file_path = os.getenv(f"{name}_FILE", "").strip()
    if file_path:
        with open(file_path, encoding="utf-8") as secret_file:
            return secret_file.read().strip()
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"missing {name} or {name}_FILE")
    return value


def main() -> None:
    username = _read_required("INITIAL_ADMIN_USERNAME")
    password = _read_required("INITIAL_ADMIN_PASSWORD")
    if not re.fullmatch(r"[\w\u4e00-\u9fff]{2,20}", username):
        raise RuntimeError("INITIAL_ADMIN_USERNAME must contain 2-20 letters, digits, underscores or Chinese characters")
    if len(password) < 12:
        raise RuntimeError("INITIAL_ADMIN_PASSWORD must contain at least 12 characters")

    db = SessionLocal()
    try:
        ensure_system_levels(db)
        user = db.query(User).filter(User.username == username).first()
        if user is None:
            user = User(
                username=username,
                nickname=username,
                password=hash_password(password),
                level_id=NORMAL_LEVEL_ID,
                is_admin=True,
            )
            db.add(user)
            action = "created"
        else:
            user.password = hash_password(password)
            user.is_admin = True
            user.token_version = int(user.token_version or 0) + 1
            action = "promoted and password rotated"
        db.commit()
        print(f"administrator {action}: {username}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
