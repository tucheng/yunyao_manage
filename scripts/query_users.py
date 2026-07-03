"""Query local MySQL users."""
from sqlalchemy import create_engine, text

eng = create_engine("mysql+pymysql://root:***@localhost:3306/yunyao?charset=utf8mb4", pool_pre_ping=True)
with eng.connect() as conn:
    rows = conn.execute(text("SELECT id,nickname,email,phone FROM users ORDER BY id"))
    for r in rows:
        print(f"ID:{r[0]}  Nick:{r[1]}  Email:{r[2]}  Phone:{r[3]}")
