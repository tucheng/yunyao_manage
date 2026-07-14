"""Canonical image URL and image-list handling shared by API routes."""

import json
import re
from urllib.parse import urlsplit


_IMAGE_URL_RE = re.compile(
    r"https?://[^\s\"',\]]+|/?uploads/[^\s\"',\]]+|/media/[^\s\"',\]]+",
    re.IGNORECASE,
)


def normalize_image_url(value) -> str:
    raw = str(value or "").strip().strip("\"'")
    if not raw:
        return ""
    raw = raw.rstrip(",]")

    if raw.startswith(("http://", "https://")):
        parsed = urlsplit(raw)
        path = parsed.path or ""
        if path.startswith(("/uploads/", "/media/")):
            return path
        return raw

    raw = raw.replace("\\", "/")
    if raw.startswith(("/api/uploads/", "api/uploads/")):
        return ""
    if raw.startswith(("/uploads/", "/media/")):
        return raw
    if raw.startswith(("uploads/", "media/")):
        return "/" + raw
    if "/" not in raw and re.search(r"\.(?:jpe?g|png|gif|webp|bmp)$", raw, re.IGNORECASE):
        return "/uploads/" + raw
    return raw


def parse_image_list(value) -> list[str]:
    if isinstance(value, (list, tuple)):
        candidates = list(value)
    elif not value:
        candidates = []
    else:
        raw = str(value).strip()
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            parsed = None
        if isinstance(parsed, list):
            candidates = parsed
        elif isinstance(parsed, str):
            candidates = [parsed]
        else:
            candidates = _IMAGE_URL_RE.findall(raw)
            if not candidates and raw:
                candidates = [raw]

    result: list[str] = []
    for candidate in candidates:
        normalized = normalize_image_url(candidate)
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def serialize_image_list(value) -> str:
    return json.dumps(parse_image_list(value), ensure_ascii=False)
