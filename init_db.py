"""
数据库初始化脚本
运行：python init_db.py

初始化预置数据：
  - 作品属性可选值（WorkAttributeOption）
  - 验证码配置默认值（AppSetting）
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from database import SessionLocal, engine, Base
from models import WorkAttributeOption, AppSetting
from sqlalchemy import text

# ===== 预置数据 =====

DEFAULT_WORK_ATTRIBUTES = {
    "type": ["透明釉", "单色釉", "立体釉", "复合釉", "釉下彩", "釉上彩", "其他"],
    "body_material": ["高白泥", "黑陶泥", "紫砂泥", "瓷泥", "陶泥", "粗陶", "红陶", "瓦胎"],
    "kiln_type": ["电窑", "气窑", "柴窑", "乐烧"],
    "surface": ["亮光", "丝光", "蜡光", "柔光", "无光", "磨砂"],
    "transparency": ["高透", "微透", "半透", "不透"],
}

DEFAULT_VERIFICATION_SETTINGS = {
    "verification_account_mode": "either",
    "verification_channel": "debug",
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
    "sms_body_template": '{"phone":"{{phone}}","code":"{{code}}"}',
}

DEFAULT_TEMPERATURE_RANGES = [
    {"value": "low", "label": "低温", "min": 0, "max": 1150, "description": "0~1150℃"},
    {"value": "mid", "label": "中温", "min": 1150, "max": 1250, "description": "1150~1250℃"},
    {"value": "high", "label": "高温", "min": 1250, "max": 1400, "description": "1250~1400℃"},
]

DEFAULT_COLOR_RANGES = [
    {"value": "cyan", "label": "青色", "names": ["天青", "粉青", "梅子青", "豆青", "翠青"], "description": "青釉系"},
    {"value": "white", "label": "白色", "names": ["甜白", "象牙白", "月白", "卵白"], "description": "白釉系"},
    {"value": "black", "label": "黑色", "names": ["乌金", "铁黑", "黑釉"], "description": "黑釉系"},
    {"value": "red", "label": "红色", "names": ["祭红", "郎红", "胭脂红", "珊瑚红"], "description": "红釉系"},
    {"value": "blue", "label": "蓝色", "names": ["霁蓝", "天蓝", "孔雀蓝"], "description": "蓝釉系"},
    {"value": "green", "label": "绿色", "names": ["翠绿", "松石绿", "孔雀绿"], "description": "绿釉系"},
    {"value": "yellow", "label": "黄色", "names": ["娇黄", "鸡油黄", "鳝鱼黄"], "description": "黄釉系"},
    {"value": "brown", "label": "棕色", "names": ["赭色", "酱釉", "柿釉"], "description": "棕釉系"},
]


def init_work_attributes(db) -> int:
    """初始化作品属性可选值，已有则跳过"""
    count = db.query(WorkAttributeOption).count()
    if count > 0:
        return 0
    total = 0
    for cat, values in DEFAULT_WORK_ATTRIBUTES.items():
        for i, v in enumerate(values):
            db.add(WorkAttributeOption(category=cat, value=v, sort_order=i))
            total += 1
    db.commit()
    return total


def init_verification_settings(db) -> int:
    """初始化验证码配置，已有则跳过"""
    count = db.query(AppSetting).filter(AppSetting.key == "verification_settings").count()
    if count > 0:
        return 0
    import json
    setting = AppSetting(key="verification_settings", value=json.dumps(DEFAULT_VERIFICATION_SETTINGS, ensure_ascii=False))
    db.add(setting)
    db.commit()
    return 1


def init_work_search_settings(db) -> int:
    """初始化作品搜索配置（温度/颜色范围），已有则跳过"""
    import json
    count = db.query(AppSetting).filter(AppSetting.key == "work_search_temperature_ranges").count()
    if count > 0:
        return 0
    t_setting = AppSetting(key="work_search_temperature_ranges", value=json.dumps(DEFAULT_TEMPERATURE_RANGES, ensure_ascii=False))
    c_setting = AppSetting(key="work_search_color_ranges", value=json.dumps(DEFAULT_COLOR_RANGES, ensure_ascii=False))
    db.add(t_setting)
    db.add(c_setting)
    db.commit()
    return 2


def main():
    # 1. 自动建表（不会覆盖已有表）
    Base.metadata.create_all(bind=engine)
    print("✅ 数据表已就绪")

    db = SessionLocal()
    try:
        results = []
        n = init_work_attributes(db)
        if n:
            results.append(f"作品属性选项: {n} 条")

        n = init_verification_settings(db)
        if n:
            results.append(f"验证码配置: 已初始化")

        n = init_work_search_settings(db)
        if n:
            results.append(f"作品搜索配置: 已初始化")

        if results:
            print("✅ 初始化完成：")
            for r in results:
                print(f"   • {r}")
        else:
            print("ℹ️  所有数据已存在，无需初始化")
    finally:
        db.close()


if __name__ == "__main__":
    main()
