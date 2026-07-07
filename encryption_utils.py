"""个人信息加密工具

使用 Fernet 对称加密来保护存储的手机号和邮箱。
查询时使用 SHA-256 哈希做精确匹配（登录、唯一性校验）。
"""
import hashlib
import os

from cryptography.fernet import Fernet


def _load_key() -> bytes:
    """从 .encryption_key 文件加载 Fernet 密钥"""
    key_path = os.path.join(os.path.dirname(__file__), ".encryption_key")
    with open(key_path) as f:
        return f.read().strip().encode()


_cipher = Fernet(_load_key())


def encrypt(plaintext: str) -> str:
    """加密明文（邮箱/手机号），空值返回空"""
    if not plaintext:
        return ""
    return _cipher.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """解密密文，空值返回空"""
    if not ciphertext:
        return ""
    return _cipher.decrypt(ciphertext.encode()).decode()


def hash_for_lookup(value: str) -> str:
    """生成用于查询的 SHA-256 哈希值（统一小写去空格）"""
    if not value:
        return ""
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()
