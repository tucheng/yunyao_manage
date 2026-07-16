"""Storage abstraction for local development and S3-compatible production storage."""

import hashlib
import hmac
import mimetypes
import os
import time
from pathlib import Path
from urllib.parse import quote

from app_config import (
    AUTH_SECRET,
    LOCAL_UPLOAD_DIR,
    S3_ACCESS_KEY_ID,
    S3_BUCKET,
    S3_PRIVATE_BUCKET,
    S3_ENDPOINT_URL,
    S3_PUBLIC_BASE_URL,
    S3_REGION,
    S3_SECRET_ACCESS_KEY,
    STORAGE_BACKEND,
)

PRIVATE_PREFIX = "private://"
PRIVATE_ROOT = Path(os.path.dirname(__file__), "private_uploads")


def _s3_client():
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("S3 storage requires boto3") from exc
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT_URL or None,
        region_name=S3_REGION,
        aws_access_key_id=S3_ACCESS_KEY_ID,
        aws_secret_access_key=S3_SECRET_ACCESS_KEY,
    )


def save_object(key: str, content: bytes, content_type: str) -> str:
    """Persist an object and return its browser-facing URL."""
    clean_key = key.replace("\\", "/").lstrip("/")
    if STORAGE_BACKEND == "s3":
        _s3_client().put_object(
            Bucket=S3_BUCKET,
            Key=clean_key,
            Body=content,
            ContentType=content_type,
            CacheControl="public, max-age=31536000, immutable",
        )
        return f"{S3_PUBLIC_BASE_URL}/{quote(clean_key, safe='/')}"

    target = Path(LOCAL_UPLOAD_DIR, clean_key).resolve()
    root = Path(LOCAL_UPLOAD_DIR).resolve()
    if os.path.commonpath((str(root), str(target))) != str(root):
        raise ValueError("invalid storage key")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return f"/uploads/{quote(clean_key, safe='/')}"


def _clean_private_key(key: str) -> str:
    clean_key = key.replace("\\", "/").lstrip("/")
    if not clean_key.startswith("complaints/") or ".." in clean_key.split("/"):
        raise ValueError("invalid private storage key")
    return clean_key


def save_private_object(key: str, content: bytes, content_type: str) -> str:
    """Persist a non-public object and return an internal database reference."""
    clean_key = _clean_private_key(key)
    if STORAGE_BACKEND == "s3":
        _s3_client().put_object(
            Bucket=S3_PRIVATE_BUCKET,
            Key=clean_key,
            Body=content,
            ContentType=content_type,
            CacheControl="private, no-store",
        )
    else:
        target = Path(PRIVATE_ROOT, clean_key).resolve()
        root = PRIVATE_ROOT.resolve()
        if os.path.commonpath((str(root), str(target))) != str(root):
            raise ValueError("invalid private storage key")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return f"{PRIVATE_PREFIX}{clean_key}"


def is_private_reference(value: str) -> bool:
    return value.startswith(PRIVATE_PREFIX)


def private_object_url(reference: str, ttl_seconds: int = 300) -> str:
    if not is_private_reference(reference):
        return reference
    key = _clean_private_key(reference[len(PRIVATE_PREFIX):])
    expires = int(time.time()) + ttl_seconds
    payload = f"{key}:{expires}".encode()
    signature = hmac.new(AUTH_SECRET.encode(), payload, hashlib.sha256).hexdigest()
    return f"/complaint-media/{quote(key, safe='/')}?expires={expires}&signature={signature}"


def read_private_object(key: str, expires: int, signature: str) -> tuple[bytes, str]:
    clean_key = _clean_private_key(key)
    if expires < int(time.time()):
        raise PermissionError("private object URL expired")
    expected = hmac.new(
        AUTH_SECRET.encode(), f"{clean_key}:{expires}".encode(), hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise PermissionError("invalid private object signature")
    if STORAGE_BACKEND == "s3":
        response = _s3_client().get_object(Bucket=S3_PRIVATE_BUCKET, Key=clean_key)
        return response["Body"].read(), response.get("ContentType") or "application/octet-stream"
    target = Path(PRIVATE_ROOT, clean_key).resolve()
    root = PRIVATE_ROOT.resolve()
    if os.path.commonpath((str(root), str(target))) != str(root) or not target.is_file():
        raise FileNotFoundError(clean_key)
    return target.read_bytes(), mimetypes.guess_type(target.name)[0] or "application/octet-stream"


def storage_healthcheck() -> None:
    if STORAGE_BACKEND == "s3":
        _s3_client().head_bucket(Bucket=S3_BUCKET)
        _s3_client().head_bucket(Bucket=S3_PRIVATE_BUCKET)
        return
    root = Path(LOCAL_UPLOAD_DIR)
    root.mkdir(parents=True, exist_ok=True)
    if not os.access(root, os.W_OK):
        raise RuntimeError("local upload directory is not writable")
