"""Bounded upload reading and defensive image normalization."""

from __future__ import annotations

import asyncio
from io import BytesIO

from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

CHUNK_SIZE = 64 * 1024
MAX_PIXELS = 20_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


async def read_upload_limited(file: UploadFile, max_bytes: int) -> bytes:
    """Read in bounded chunks and reject before buffering more than max_bytes."""
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(CHUNK_SIZE):
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(status_code=413, detail=f"图片不能超过 {max_bytes // 1024 // 1024}MB")
        chunks.append(chunk)
    if not chunks:
        raise HTTPException(status_code=400, detail="请选择图片")
    return b"".join(chunks)


def _normalize_image(content: bytes, allowed_formats: set[str], max_dimension: int) -> tuple[bytes, str, str]:
    try:
        with Image.open(BytesIO(content)) as source:
            source.load()
            fmt = (source.format or "").upper()
            if fmt not in allowed_formats:
                raise HTTPException(status_code=400, detail="不支持的图片格式")
            width, height = source.size
            if width < 1 or height < 1 or width > max_dimension or height > max_dimension:
                raise HTTPException(status_code=400, detail=f"图片边长不能超过 {max_dimension} 像素")
            if width * height > MAX_PIXELS:
                raise HTTPException(status_code=400, detail="图片像素总数过大")

            # Rebuild pixel data into a new object. This drops EXIF, ICC, comments,
            # additional frames and trailing/polyglot payloads.
            clean = ImageOps.exif_transpose(source)
            output = BytesIO()
            if fmt == "JPEG":
                clean = clean.convert("RGB")
                clean.save(output, "JPEG", quality=90, optimize=True)
                return output.getvalue(), ".jpg", "image/jpeg"
            if fmt == "WEBP":
                clean = clean.convert("RGBA" if "A" in clean.getbands() else "RGB")
                clean.save(output, "WEBP", quality=90, method=4)
                return output.getvalue(), ".webp", "image/webp"
            clean = clean.convert("RGBA" if "A" in clean.getbands() else "RGB")
            clean.save(output, "PNG", optimize=True)
            return output.getvalue(), ".png", "image/png"
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise HTTPException(status_code=400, detail="图片解码失败") from exc


async def sanitize_image(
    file: UploadFile,
    *,
    max_bytes: int,
    allowed_formats: set[str],
    max_dimension: int,
) -> tuple[bytes, str, str]:
    content = await read_upload_limited(file, max_bytes)
    normalized = await asyncio.to_thread(_normalize_image, content, allowed_formats, max_dimension)
    if len(normalized[0]) > max_bytes:
        raise HTTPException(status_code=413, detail=f"重新编码后的图片不能超过 {max_bytes // 1024 // 1024}MB")
    return normalized
