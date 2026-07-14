"""Finish the pre-production image migration and remove obsolete local files.

This migration intentionally does not preserve invalid legacy references. It imports
the allow-listed Unsplash seed images when they still exist, removes dead/blob URLs,
moves non-recipe images to ``uploads/misc``, and purges unreferenced root files.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import shutil
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

import requests
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app_config import LOCAL_UPLOAD_DIR, STORAGE_BACKEND  # noqa: E402
from database import SessionLocal  # noqa: E402
from image_utils import normalize_image_url, parse_image_list, serialize_image_list  # noqa: E402
from models import Complaint, Recipe, Review, User, Work  # noqa: E402

ALLOWED_EXTERNAL_HOSTS = {"images.unsplash.com"}
ALLOWED_IMAGE_FORMATS = {"JPEG": ".jpg", "PNG": ".png", "GIF": ".gif", "WEBP": ".webp"}


def _safe_target(upload_root: Path, key: str) -> Path:
    target = (upload_root / key).resolve()
    if os.path.commonpath((str(upload_root), str(target))) != str(upload_root):
        raise ValueError(f"unsafe upload key: {key}")
    return target


def _root_local_key(value: str) -> str | None:
    normalized = normalize_image_url(value)
    if not normalized.startswith("/uploads/"):
        return None
    key = unquote(normalized[len("/uploads/"):]).replace("\\", "/").lstrip("/")
    if not key or "/" in key or ".." in Path(key).parts:
        return None
    return key


def _download_seed_image(url: str, upload_root: Path, apply: bool, stats: dict) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in ALLOWED_EXTERNAL_HOSTS:
        stats["removed_external"] += 1
        return ""
    if not apply:
        stats["external_candidates"] += 1
        return url

    try:
        response = requests.get(url, timeout=30, headers={"User-Agent": "YunyaoImageMigration/1.0"})
        response.raise_for_status()
        content = response.content
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
            extension = ALLOWED_IMAGE_FORMATS.get(image.format or "")
        if not extension:
            raise ValueError("unsupported image format")
    except Exception:
        stats["removed_external"] += 1
        return ""

    digest = hashlib.sha256(content).hexdigest()[:24]
    key = f"recipes/legacy-{digest}{extension}"
    target = _safe_target(upload_root, key)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(content)
        stats["downloaded_external"] += 1
    return f"/uploads/{key}"


def _import_data_image(value: str, upload_root: Path, apply: bool, stats: dict) -> str:
    if not value.startswith("data:image/") or ";base64," not in value:
        return ""
    if not apply:
        stats["data_image_candidates"] += 1
        return value
    try:
        content = base64.b64decode(value.split(",", 1)[1], validate=True)
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
            extension = ALLOWED_IMAGE_FORMATS.get(image.format or "")
        if not extension:
            raise ValueError("unsupported image format")
    except Exception:
        stats["removed_work_external"] += 1
        return ""
    digest = hashlib.sha256(content).hexdigest()[:24]
    key = f"works/legacy-{digest}{extension}"
    target = _safe_target(upload_root, key)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(content)
        stats["imported_data_images"] += 1
    return f"/uploads/{key}"


def _migrate_misc_value(value: str, upload_root: Path, apply: bool, copies: set[tuple[Path, Path]]) -> str:
    normalized = normalize_image_url(value)
    key = _root_local_key(normalized)
    if not key:
        return normalized
    source = _safe_target(upload_root, key)
    if not source.is_file():
        return ""
    destination = _safe_target(upload_root, f"misc/{key}")
    copies.add((source, destination))
    return f"/uploads/misc/{key}"


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except PermissionError:
        path.chmod(0o666)
        path.unlink()


def run(apply: bool) -> dict:
    if STORAGE_BACKEND != "local":
        raise RuntimeError("This migration only supports STORAGE_BACKEND=local")

    upload_root = Path(LOCAL_UPLOAD_DIR).resolve()
    stats = {
        "recipes_changed": 0,
        "works_changed": 0,
        "external_candidates": 0,
        "downloaded_external": 0,
        "removed_external": 0,
        "removed_blob_urls": 0,
        "data_image_candidates": 0,
        "imported_data_images": 0,
        "removed_work_external": 0,
        "misc_records_changed": 0,
        "misc_files_copied": 0,
        "root_files_deleted": 0,
    }
    copies: set[tuple[Path, Path]] = set()
    external_cache: dict[str, str] = {}
    db = SessionLocal()
    try:
        for recipe in db.query(Recipe).all():
            old_cover = recipe.cover or ""
            old_images = recipe.images or "[]"

            def migrate(value: str) -> str:
                normalized = normalize_image_url(value)
                if normalized.startswith("blob:"):
                    stats["removed_blob_urls"] += 1
                    return ""
                if normalized.startswith(("http://", "https://")):
                    if normalized not in external_cache:
                        external_cache[normalized] = _download_seed_image(normalized, upload_root, apply, stats)
                    return external_cache[normalized]
                return normalized

            images = [result for value in parse_image_list(old_images) if (result := migrate(value))]
            cover = migrate(old_cover)
            if cover and cover not in images:
                images.insert(0, cover)
            if not cover and images:
                cover = images[0]
            images = list(dict.fromkeys(images))
            serialized = json.dumps(images, ensure_ascii=False)
            if cover != old_cover or serialized != old_images:
                stats["recipes_changed"] += 1
                recipe.cover = cover
                recipe.images = serialized

        for work in db.query(Work).all():
            old_image = work.image or ""
            old_images = work.images or "[]"

            def migrate_work(value: str) -> str:
                normalized = normalize_image_url(value)
                if normalized.startswith("data:image/"):
                    return _import_data_image(normalized, upload_root, apply, stats)
                if normalized.startswith(("blob:", "http://", "https://")):
                    stats["removed_work_external"] += 1
                    return ""
                return normalized

            images = [result for value in parse_image_list(old_images) if (result := migrate_work(value))]
            image = migrate_work(old_image)
            if image and image not in images:
                images.insert(0, image)
            if not image and images:
                image = images[0]
            images = list(dict.fromkeys(images))
            serialized = json.dumps(images, ensure_ascii=False)
            if image != old_image or serialized != old_images:
                stats["works_changed"] += 1
                work.image = image
                work.images = serialized

        for user in db.query(User).all():
            migrated = _migrate_misc_value(user.avatar, upload_root, apply, copies)
            if migrated != (user.avatar or ""):
                user.avatar = migrated
                stats["misc_records_changed"] += 1

        for review in db.query(Review).all():
            migrated = _migrate_misc_value(review.image, upload_root, apply, copies)
            if migrated != (review.image or ""):
                review.image = migrated
                stats["misc_records_changed"] += 1

        for complaint in db.query(Complaint).all():
            old_images = complaint.images or ""
            images = [
                migrated
                for value in parse_image_list(old_images)
                if (migrated := _migrate_misc_value(value, upload_root, apply, copies))
            ]
            serialized = serialize_image_list(images) if images else ""
            if serialized != old_images:
                complaint.images = serialized
                stats["misc_records_changed"] += 1

        if apply:
            for source, destination in copies:
                destination.parent.mkdir(parents=True, exist_ok=True)
                if not destination.exists():
                    shutil.copy2(source, destination)
                    stats["misc_files_copied"] += 1
            db.commit()

            # All active references now point into recipes/, works/, or misc/.
            for path in list(upload_root.iterdir()):
                if path.is_file():
                    _unlink(path)
                    stats["root_files_deleted"] += 1
        else:
            db.rollback()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps({"mode": "apply" if args.apply else "dry-run", **run(args.apply)}, ensure_ascii=False, indent=2))
