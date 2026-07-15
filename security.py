"""Versioned application encryption and stable lookup hashing.

Ciphertext format: ``enc:v1:<key-id>:<fernet-token>``.  The key id makes
rotation deterministic; all configured keys remain decrypt-only candidates.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app_config import (
    ENCRYPTION_ACTIVE_KEY_ID,
    ENCRYPTION_KEY_FILE,
    ENCRYPTION_KEYS,
    PERSONAL_DATA_ENCRYPTION_KEY,
    RECIPE_ENCRYPT_KEY,
)

PREFIX = "enc:v1:"


class EncryptionError(ValueError):
    """Raised when ciphertext is malformed or cannot be decrypted."""


def _derive_legacy_recipe_key(password: str) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(), length=32, salt=b"xiacaifang_salt_v1", iterations=100000,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode()))


@lru_cache(maxsize=1)
def _keyring() -> tuple[str, dict[str, Fernet]]:
    raw: dict[str, str] = {}
    if ENCRYPTION_KEYS:
        try:
            parsed = json.loads(ENCRYPTION_KEYS)
            if not isinstance(parsed, dict):
                raise TypeError
            raw.update({str(key): str(value) for key, value in parsed.items()})
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("ENCRYPTION_KEYS 必须是 key-id 到 Fernet key 的 JSON 对象") from exc
    if PERSONAL_DATA_ENCRYPTION_KEY:
        raw.setdefault("legacy-pii", PERSONAL_DATA_ENCRYPTION_KEY)
    if RECIPE_ENCRYPT_KEY:
        raw.setdefault("legacy-recipe", _derive_legacy_recipe_key(RECIPE_ENCRYPT_KEY).decode())
    if ENCRYPTION_KEY_FILE and os.path.isfile(ENCRYPTION_KEY_FILE):
        with open(ENCRYPTION_KEY_FILE, encoding="ascii") as key_file:
            raw.setdefault("legacy-file", key_file.read().strip())
    if not raw:
        raise RuntimeError("没有可用的加密密钥")
    active = ENCRYPTION_ACTIVE_KEY_ID
    if active not in raw:
        # Backward-compatible startup when a single legacy key is configured.
        if active == "primary" and "legacy-pii" in raw:
            active = "legacy-pii"
        elif active == "primary" and "legacy-recipe" in raw:
            active = "legacy-recipe"
        elif len(raw) == 1:
            active = next(iter(raw))
        else:
            raise RuntimeError(f"ENCRYPTION_ACTIVE_KEY_ID={active!r} 不在 ENCRYPTION_KEYS 中")
    try:
        return active, {key_id: Fernet(value.encode("ascii")) for key_id, value in raw.items()}
    except (ValueError, TypeError) as exc:
        raise RuntimeError("加密密钥不是有效的 Fernet key") from exc


def encrypt(plaintext: str) -> str:
    if not plaintext:
        return ""
    active, keys = _keyring()
    token = keys[active].encrypt(plaintext.encode()).decode()
    return f"{PREFIX}{active}:{token}"


def decrypt(ciphertext: str, *, allow_plaintext: bool = False) -> str:
    if not ciphertext:
        return ""
    _active, keys = _keyring()
    if ciphertext.startswith(PREFIX):
        try:
            key_id, token = ciphertext[len(PREFIX):].split(":", 1)
        except ValueError as exc:
            raise EncryptionError("密文版本头格式错误") from exc
        cipher = keys.get(key_id)
        if cipher is None:
            raise EncryptionError(f"密文使用了未配置的密钥: {key_id}")
        try:
            return cipher.decrypt(token.encode()).decode()
        except (InvalidToken, UnicodeDecodeError) as exc:
            raise EncryptionError("密文校验或解密失败") from exc

    # Legacy Fernet values had no version prefix. Try every retained key.
    for cipher in keys.values():
        try:
            return cipher.decrypt(ciphertext.encode()).decode()
        except (InvalidToken, UnicodeDecodeError):
            continue
    if allow_plaintext and not ciphertext.startswith("gAAAA"):
        return ciphertext
    raise EncryptionError("无法解密旧版密文；未将密文作为明文返回")


def is_encrypted(value: str) -> bool:
    if not value:
        return False
    try:
        decrypt(value)
        return True
    except EncryptionError:
        return False


def needs_rotation(value: str) -> bool:
    active, _keys = _keyring()
    return not value.startswith(f"{PREFIX}{active}:")


def rotate(value: str) -> str:
    return encrypt(decrypt(value)) if needs_rotation(value) else value


def hash_for_lookup(value: str) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()
