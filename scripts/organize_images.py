"""Move existing recipe/work images into canonical folders and rewrite the DB.

Run without arguments for a report, then use ``--apply`` to commit changes.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app_config import LOCAL_UPLOAD_DIR, STORAGE_BACKEND  # noqa: E402
from database import SessionLocal  # noqa: E402
from image_utils import normalize_image_url, parse_image_list  # noqa: E402
from models import Complaint, Recipe, Review, User, Work  # noqa: E402


def _local_key(value: str) -> str | None:
    normalized = normalize_image_url(value)
    if not normalized:
        return None
    if normalized.startswith(("http://", "https://")):
        path = urlsplit(normalized).path
    else:
        path = normalized
    if not path.startswith("/uploads/"):
        return None
    key = unquote(path[len("/uploads/"):]).replace("\\", "/").lstrip("/")
    parts = Path(key).parts
    if not key or ".." in parts:
        return None
    return key


def _destination_key(source_key: str, folder: str) -> str:
    source = Path(source_key)
    if source.parts and source.parts[0].lower() == folder:
        return source_key.replace("\\", "/")
    return f"{folder}/{source.name}"


def _migrate_url(value: str, folder: str, upload_root: Path, stats: dict) -> str:
    normalized = normalize_image_url(value)
    if not normalized:
        return ""
    source_key = _local_key(normalized)
    if source_key is None:
        return normalized

    source = (upload_root / source_key).resolve()
    if os.path.commonpath((str(upload_root), str(source))) != str(upload_root):
        stats["invalid"] += 1
        return ""
    if not source.is_file():
        stats["missing"] += 1
        return ""

    destination_key = _destination_key(source_key, folder)
    destination = (upload_root / destination_key).resolve()
    if destination.exists() and destination.read_bytes() != source.read_bytes():
        destination_key = f"{folder}/{source.stem}-{abs(hash(source_key)) & 0xFFFFFFFF:08x}{source.suffix}"
        destination = (upload_root / destination_key).resolve()
    stats["copies"].add((source, destination))
    return f"/uploads/{destination_key.replace(os.sep, '/')}"


def _protected_keys(db) -> set[str]:
    values: list[str] = []
    values.extend(row.avatar for row in db.query(User.avatar).all() if row.avatar)
    values.extend(row.image for row in db.query(Review.image).all() if row.image)
    for row in db.query(Complaint.images).all():
        values.extend(parse_image_list(row.images))
    return {key for value in values if (key := _local_key(value))}


def run(apply: bool) -> dict:
    if STORAGE_BACKEND != "local":
        raise RuntimeError("This migration only supports STORAGE_BACKEND=local")

    upload_root = Path(LOCAL_UPLOAD_DIR).resolve()
    upload_root.mkdir(parents=True, exist_ok=True)
    stats = {
        "recipes": 0,
        "works": 0,
        "missing": 0,
        "invalid": 0,
        "copies": set(),
        "deleted_sources": 0,
    }

    db = SessionLocal()
    try:
        protected = _protected_keys(db)
        for recipe in db.query(Recipe).all():
            original_cover = recipe.cover or ""
            original_images = recipe.images or "[]"
            migrated = [
                result
                for value in parse_image_list(original_images)
                if (result := _migrate_url(value, "recipes", upload_root, stats))
            ]
            cover = _migrate_url(original_cover, "recipes", upload_root, stats)
            if cover and cover not in migrated:
                migrated.insert(0, cover)
            if not cover and migrated:
                cover = migrated[0]
            serialized = json.dumps(list(dict.fromkeys(migrated)), ensure_ascii=False)
            if cover != original_cover or serialized != original_images:
                stats["recipes"] += 1
                recipe.cover = cover
                recipe.images = serialized

        for work in db.query(Work).all():
            original_image = work.image or ""
            original_images = work.images or "[]"
            migrated = [
                result
                for value in parse_image_list(original_images)
                if (result := _migrate_url(value, "works", upload_root, stats))
            ]
            image = _migrate_url(original_image, "works", upload_root, stats)
            if image and image not in migrated:
                migrated.insert(0, image)
            if not image and migrated:
                image = migrated[0]
            serialized = json.dumps(list(dict.fromkeys(migrated)), ensure_ascii=False)
            if image != original_image or serialized != original_images:
                stats["works"] += 1
                work.image = image
                work.images = serialized

        if apply:
            for source, destination in stats["copies"]:
                destination.parent.mkdir(parents=True, exist_ok=True)
                if source != destination and not destination.exists():
                    shutil.copy2(source, destination)
            db.commit()

            for source, destination in stats["copies"]:
                if source == destination or not source.is_file():
                    continue
                relative = source.relative_to(upload_root).as_posix()
                if relative in protected or relative.startswith(("recipes/", "works/")):
                    continue
                try:
                    source.unlink()
                except PermissionError:
                    source.chmod(0o666)
                    source.unlink()
                stats["deleted_sources"] += 1

            # A prior interrupted run may already have committed the new DB paths.
            # Remove only root-level originals that have an identical canonical copy.
            for source in upload_root.iterdir():
                if not source.is_file() or source.name in protected:
                    continue
                candidates = (upload_root / "recipes" / source.name, upload_root / "works" / source.name)
                if not any(candidate.is_file() and candidate.read_bytes() == source.read_bytes() for candidate in candidates):
                    continue
                try:
                    source.unlink()
                except PermissionError:
                    source.chmod(0o666)
                    source.unlink()
                stats["deleted_sources"] += 1
        else:
            db.rollback()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    stats["copies"] = len(stats["copies"])
    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="copy files and commit DB changes")
    args = parser.parse_args()
    result = run(args.apply)
    print(json.dumps({"mode": "apply" if args.apply else "dry-run", **result}, ensure_ascii=False, indent=2))
