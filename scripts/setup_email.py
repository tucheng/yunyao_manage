"""Create app_settings table and insert SMTP config for 163 email."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Build engine directly with url-encoded password
engine = create_engine(
    "mysql+pymysql://yunyao:Yunyao%402024@localhost:3306/yunyao?charset=utf8mb4",
    pool_pre_ping=True
)

from database import Base
import models  # noqa: F401 - registers all models

# Create all tables (safe - IF NOT EXISTS)
Base.metadata.create_all(bind=engine)
print("Tables created successfully")

# Insert SMTP settings
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
from models import AppSetting

db = SessionLocal()
settings = [
    ("verification_channel", "email"),
    ("smtp_host", "smtp.163.com"),
    ("smtp_port", "465"),
    ("smtp_username", "allow26@163.com"),
    ("smtp_password", "HQmzYM6yqwhgXyaB"),
    ("smtp_from", "allow26@163.com"),
    ("smtp_use_ssl", "1"),
    ("email_subject", "\u4e91\u7aaf\u9a8c\u8bc1\u7801"),
    ("email_body_template", "\u60a8\u7684\u9a8c\u8bc1\u7801\u662f {{code}}\uff0c10\u5206\u949f\u5185\u6709\u6548\u3002"),
]
for key, value in settings:
    existing = db.query(AppSetting).filter(AppSetting.key == key).first()
    if existing:
        existing.value = value
    else:
        db.add(AppSetting(key=key, value=value))
db.commit()
db.close()
print("SMTP settings saved")

# Verify
from verification_sender import get_settings
db2 = SessionLocal()
s = get_settings(db2, mask_sensitive=True)
db2.close()
for k, v in s.items():
    print(f"  {k}: {v}")
