"""Inventory and migrate local uploads to S3. Dry-run is the default; never deletes source files."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app_config import LOCAL_UPLOAD_DIR, S3_BUCKET
from storage import _s3_client


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=LOCAL_UPLOAD_DIR)
    parser.add_argument("--manifest", default="uploads-migration-manifest.ndjson")
    parser.add_argument("--execute", action="store_true", help="upload and verify; sources are retained")
    args = parser.parse_args()

    root = Path(args.source).resolve()
    if not root.is_dir():
        raise SystemExit(f"upload directory not found: {root}")
    client = _s3_client() if args.execute else None
    total_bytes = 0
    count = 0
    with Path(args.manifest).open("w", encoding="utf-8") as manifest:
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            key = path.relative_to(root).as_posix()
            size = path.stat().st_size
            checksum = sha256(path)
            record = {"key": key, "size": size, "sha256": checksum, "status": "inventory"}
            if client is not None:
                content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                client.upload_file(
                    str(path), S3_BUCKET, key,
                    ExtraArgs={"ContentType": content_type, "Metadata": {"sha256": checksum}},
                )
                head = client.head_object(Bucket=S3_BUCKET, Key=key)
                if head["ContentLength"] != size or head.get("Metadata", {}).get("sha256") != checksum:
                    raise RuntimeError(f"verification failed: {key}")
                record["status"] = "uploaded_verified"
            manifest.write(json.dumps(record, ensure_ascii=False) + "\n")
            total_bytes += size
            count += 1
    print(json.dumps({"files": count, "bytes": total_bytes, "execute": args.execute, "manifest": args.manifest}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
