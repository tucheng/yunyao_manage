import asyncio
import base64
import time

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app_config import BAIDU_OCR_API_KEY, BAIDU_OCR_API_URL, BAIDU_OCR_SECRET_KEY, BAIDU_OCR_TOKEN_URL
from auth_utils import current_user
from image_security import sanitize_image

router = APIRouter(prefix="/ocr", tags=["文字识别"], dependencies=[Depends(current_user)])

MAX_FILE_SIZE = 3 * 1024 * 1024
_token = ""
_token_expires_at = 0.0
_token_lock = asyncio.Lock()


def _credentials() -> tuple[str, str]:
    if not BAIDU_OCR_API_KEY or not BAIDU_OCR_SECRET_KEY:
        raise HTTPException(status_code=503, detail="OCR 服务尚未配置")
    return BAIDU_OCR_API_KEY, BAIDU_OCR_SECRET_KEY


async def _get_access_token(client: httpx.AsyncClient, force_refresh: bool = False) -> str:
    global _token, _token_expires_at
    now = time.monotonic()
    if not force_refresh and _token and now < _token_expires_at:
        return _token
    async with _token_lock:
        now = time.monotonic()
        if not force_refresh and _token and now < _token_expires_at:
            return _token
        api_key, secret_key = _credentials()
        try:
            response = await client.post(
                BAIDU_OCR_TOKEN_URL,
                params={"grant_type": "client_credentials", "client_id": api_key, "client_secret": secret_key},
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(status_code=502, detail="OCR 鉴权服务暂时不可用") from exc
        token = data.get("access_token")
        if not token:
            raise HTTPException(status_code=502, detail="OCR 凭据验证失败")
        expires_in = max(int(data.get("expires_in", 2592000)), 300)
        _token = token
        _token_expires_at = now + expires_in - 120
        return token


async def _recognize(client: httpx.AsyncClient, token: str, content: bytes) -> httpx.Response:
    return await client.post(
        BAIDU_OCR_API_URL,
        params={"access_token": token},
        data={
            "image": base64.b64encode(content).decode("ascii"),
            "language_type": "CHN_ENG",
            "detect_direction": "true",
            "paragraph": "false",
        },
    )


@router.post("/image")
async def recognize_image(file: UploadFile = File(...)):
    content, _ext, _content_type = await sanitize_image(
        file, max_bytes=MAX_FILE_SIZE, allowed_formats={"JPEG", "PNG", "BMP"}, max_dimension=4096,
    )
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=10)) as client:
            response = await _recognize(client, await _get_access_token(client), content)
            data = response.json()
            if data.get("error_code") in (110, 111):
                response = await _recognize(client, await _get_access_token(client, force_refresh=True), content)
                data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="OCR 服务暂时不可用") from exc
    if response.status_code >= 400 or data.get("error_code"):
        raise HTTPException(status_code=502, detail=data.get("error_msg", "图片识别失败"))
    lines = [item.get("words", "").strip() for item in data.get("words_result", [])]
    lines = [line for line in lines if line]
    return {"text": "\n".join(lines), "lines": lines, "count": len(lines)}
