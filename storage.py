"""Storage abstraction for local development and S3-compatible production storage."""

import os
from pathlib import Path
from urllib.parse import quote

from app_config import (
    LOCAL_UPLOAD_DIR,
    S3_ACCESS_KEY_ID,
    S3_BUCKET,
    S3_ENDPOINT_URL,
    S3_PUBLIC_BASE_URL,
    S3_REGION,
    S3_SECRET_ACCESS_KEY,
    STORAGE_BACKEND,
)


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


def storage_healthcheck() -> None:
    if STORAGE_BACKEND == "s3":
        _s3_client().head_bucket(Bucket=S3_BUCKET)
        return
    root = Path(LOCAL_UPLOAD_DIR)
    root.mkdir(parents=True, exist_ok=True)
    if not os.access(root, os.W_OK):
        raise RuntimeError("local upload directory is not writable")
