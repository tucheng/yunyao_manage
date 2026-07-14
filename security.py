"""数据加密模块 - 对配方原料和用量进行加密存储。"""

import os
import base64
import hashlib
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from app_config import ENCRYPTION_KEY_FILE, RECIPE_ENCRYPT_KEY

KEY_FILE = ENCRYPTION_KEY_FILE
ENV_PASSWORD = RECIPE_ENCRYPT_KEY


def _get_key() -> bytes:
    """获取加密密钥"""
    if ENV_PASSWORD:
        # 用环境变量密码派生密钥
        salt = b"xiacaifang_salt_v1"
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100000)
        return base64.urlsafe_b64encode(kdf.derive(ENV_PASSWORD.encode()))

    # 文件模式：自动生成
    if not os.path.exists(KEY_FILE):
        key = Fernet.generate_key()
        with open(KEY_FILE, "wb") as f:
            f.write(key)
        os.chmod(KEY_FILE, 0o600)  # 仅 owner 可读写
    else:
        with open(KEY_FILE, "rb") as f:
            key = f.read()
    return key


def _get_cipher() -> Fernet:
    return Fernet(_get_key())


def encrypt(text: str) -> str:
    """加密文本，返回 base64 字符串"""
    if not text:
        return text
    cipher = _get_cipher()
    return cipher.encrypt(text.encode()).decode()


def decrypt(text: str) -> str:
    """解密 base64 字符串"""
    if not text:
        return text
    try:
        cipher = _get_cipher()
        return cipher.decrypt(text.encode()).decode()
    except Exception:
        # 如果不是加密数据（旧数据未加密），原样返回
        return text


def is_encrypted(text: str) -> bool:
    """判断是否是加密数据"""
    if not text:
        return False
    try:
        # 尝试解密，成功则说明是加密的
        cipher = _get_cipher()
        cipher.decrypt(text.encode())
        return True
    except Exception:
        return False


def hash_for_lookup(value: str) -> str:
    """生成用于搜索的 SHA-256 哈希值"""
    if not value:
        return ""
    return hashlib.sha256(value.strip().encode()).hexdigest()
