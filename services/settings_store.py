import json

from sqlalchemy.orm import Session

from models import AppSetting


def get_json_setting(db: Session, key: str, default):
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if not row or not row.value:
        return default
    try:
        value = json.loads(row.value)
    except (TypeError, ValueError):
        return default
    return value if isinstance(value, type(default)) else default


def set_json_setting(db: Session, key: str, value) -> None:
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if not row:
        row = AppSetting(key=key)
        db.add(row)
    row.value = json.dumps(value, ensure_ascii=False)


def ensure_json_setting(db: Session, key: str, default):
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if not row or not row.value:
        set_json_setting(db, key, default)
        db.commit()
        return default
    return get_json_setting(db, key, default)
