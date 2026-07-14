import json
import smtplib
from email.mime.text import MIMEText

import requests
from sqlalchemy.orm import Session

from app_config import IS_PRODUCTION
from models import AppSetting


DEFAULT_SETTINGS = {
    "verification_account_mode": "either",  # sms / email / either
    "verification_channel": "debug",  # debug / email / sms
    "smtp_host": "",
    "smtp_port": "465",
    "smtp_username": "",
    "smtp_password": "",
    "smtp_from": "",
    "smtp_use_ssl": "1",
    "email_subject": "云窑验证码",
    "email_body_template": "您的验证码是 {{code}}，10分钟内有效。",
    "sms_api_url": "",
    "sms_method": "POST",
    "sms_headers_json": "{}",
    "sms_body_template": "{\"phone\":\"{{phone}}\",\"code\":\"{{code}}\"}",
}

SENSITIVE_KEYS = {"smtp_password"}


def get_settings(db: Session, mask_sensitive: bool = False) -> dict[str, str]:
    settings = DEFAULT_SETTINGS.copy()
    rows = db.query(AppSetting).all()
    for row in rows:
        settings[row.key] = row.value or ""
    if mask_sensitive:
        for key in SENSITIVE_KEYS:
            if settings.get(key):
                settings[key] = "********"
    return settings


def save_settings(db: Session, values: dict[str, str]) -> dict[str, str]:
    current = get_settings(db)
    allowed = set(DEFAULT_SETTINGS)
    for key, value in values.items():
        if key not in allowed:
            continue
        if key in SENSITIVE_KEYS and value == "********":
            value = current.get(key, "")
        row = db.query(AppSetting).filter(AppSetting.key == key).first()
        if not row:
            row = AppSetting(key=key, value=str(value or ""))
            db.add(row)
        else:
            row.value = str(value or "")
    db.commit()
    return get_settings(db, mask_sensitive=True)


def render_template(template: str, *, code: str, email: str = "", phone: str = "") -> str:
    return (
        template.replace("{{code}}", code)
        .replace("{{email}}", email)
        .replace("{{phone}}", phone)
    )


def send_email_code(settings: dict[str, str], email: str, code: str) -> None:
    host = settings.get("smtp_host", "")
    username = settings.get("smtp_username", "")
    password = settings.get("smtp_password", "")
    sender = settings.get("smtp_from", "") or username
    if not host or not username or not password or not sender:
        raise RuntimeError("邮箱 SMTP 配置不完整")

    message = MIMEText(
        render_template(settings.get("email_body_template", ""), code=code, email=email),
        "plain",
        "utf-8",
    )
    message["Subject"] = settings.get("email_subject", "云窑验证码")
    message["From"] = sender
    message["To"] = email

    port = int(settings.get("smtp_port", "465") or "465")
    if settings.get("smtp_use_ssl", "1") == "1":
        with smtplib.SMTP_SSL(host, port, timeout=10) as smtp:
            smtp.login(username, password)
            smtp.sendmail(sender, [email], message.as_string())
    else:
        with smtplib.SMTP(host, port, timeout=10) as smtp:
            smtp.starttls()
            smtp.login(username, password)
            smtp.sendmail(sender, [email], message.as_string())


def send_sms_code(settings: dict[str, str], phone: str, code: str) -> None:
    url = settings.get("sms_api_url", "")
    if not url:
        raise RuntimeError("短信接口 URL 未配置")
    headers = json.loads(settings.get("sms_headers_json", "{}") or "{}")
    body_text = render_template(settings.get("sms_body_template", "{}"), code=code, phone=phone)
    try:
        body = json.loads(body_text)
    except json.JSONDecodeError:
        body = body_text
    method = settings.get("sms_method", "POST").upper()
    if method == "GET":
        response = requests.get(url, headers=headers, params=body if isinstance(body, dict) else None, timeout=10)
    else:
        response = requests.request(
            method,
            url,
            headers=headers,
            json=body if isinstance(body, dict) else None,
            data=None if isinstance(body, dict) else body,
            timeout=10,
        )
    response.raise_for_status()


def send_verification_code(db: Session, *, email: str, phone: str, code: str) -> dict[str, str]:
    settings = get_settings(db)
    channel = settings.get("verification_channel", "debug")
    if channel == "email":
        if not email:
            raise RuntimeError("当前配置为邮箱验证码，请输入邮箱")
        send_email_code(settings, email, code)
        return {"channel": "email"}
    if channel == "sms":
        if not phone:
            raise RuntimeError("当前配置为短信验证码，请输入手机号")
        send_sms_code(settings, phone, code)
        return {"channel": "sms"}
    if IS_PRODUCTION:
        raise RuntimeError("生产环境禁止使用 debug 验证码通道")
    return {"channel": "debug", "debug_code": code}
