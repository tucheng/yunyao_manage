import base64
import threading
import time
from io import BytesIO

import requests
from fastapi import APIRouter, File, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError
from app_config import (
    BAIDU_OCR_API_KEY,
    BAIDU_OCR_API_URL,
    BAIDU_OCR_SECRET_KEY,
    BAIDU_OCR_TOKEN_URL,
)

router = APIRouter(prefix="/ocr", tags=["文字识别"])

MAX_FILE_SIZE = 3 * 1024 * 1024
ALLOWED_FORMATS = {"JPEG", "PNG", "BMP"}

_token = ""
_token_expires_at = 0.0
_token_lock = threading.Lock()


def _credentials() -> tuple[str, str]:
    api_key = BAIDU_OCR_API_KEY
    secret_key = BAIDU_OCR_SECRET_KEY
    if not api_key or not secret_key:
        raise HTTPException(status_code=503, detail="OCR 服务尚未配置")
    return api_key, secret_key


def _get_access_token(force_refresh: bool = False) -> str:
    global _token, _token_expires_at
    now = time.time()
    if not force_refresh and _token and now < _token_expires_at:
        return _token

    with _token_lock:
        now = time.time()
        if not force_refresh and _token and now < _token_expires_at:
            return _token
        api_key, secret_key = _credentials()
        try:
            response = requests.post(
                BAIDU_OCR_TOKEN_URL,
                params={"grant_type": "client_credentials", "client_id": api_key, "client_secret": secret_key},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise HTTPException(status_code=502, detail="OCR 鉴权服务暂时不可用") from exc

        token = data.get("access_token")
        if not token:
            raise HTTPException(status_code=502, detail="OCR 凭据验证失败")
        expires_in = max(int(data.get("expires_in", 2592000)), 300)
        _token = token
        _token_expires_at = now + expires_in - 120
        return token


def _validate_image(content: bytes) -> None:
    if not content:
        raise HTTPException(status_code=400, detail="请选择图片")
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="图片不能超过 3MB")
    try:
        with Image.open(BytesIO(content)) as image:
            image.verify()
        with Image.open(BytesIO(content)) as image:
            if image.format not in ALLOWED_FORMATS:
                raise HTTPException(status_code=400, detail="仅支持 JPG、PNG、BMP 图片")
            width, height = image.size
            if min(width, height) < 15 or max(width, height) > 4096:
                raise HTTPException(status_code=400, detail="图片边长需在 15–4096 像素之间")
    except UnidentifiedImageError as exc:
        raise HTTPException(status_code=400, detail="图片格式不正确") from exc


@router.post("/image")
async def recognize_image(file: UploadFile = File(...)):
    content = await file.read()
    _validate_image(content)

    def call_baidu(token: str):
        return requests.post(
            BAIDU_OCR_API_URL,
            params={"access_token": token},
            data={
                "image": base64.b64encode(content).decode("ascii"),
                "language_type": "CHN_ENG",
                "detect_direction": "true",
                "paragraph": "false",
            },
            timeout=20,
        )

    try:
        response = call_baidu(_get_access_token())
        data = response.json()
        if data.get("error_code") in (110, 111):
            response = call_baidu(_get_access_token(force_refresh=True))
            data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise HTTPException(status_code=502, detail="OCR 服务暂时不可用") from exc

    if response.status_code >= 400 or data.get("error_code"):
        raise HTTPException(status_code=502, detail=data.get("error_msg", "图片识别失败"))

    lines = [item.get("words", "").strip() for item in data.get("words_result", [])]
    lines = [line for line in lines if line]
    return {"text": "\n".join(lines), "lines": lines, "count": len(lines)}
