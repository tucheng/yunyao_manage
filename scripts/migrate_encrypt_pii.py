"""迁移脚本：加密现有用户手机号和邮箱

1. 给 users 表添加 email_hash / phone_hash 列
2. 加密现有的 email / phone 数据
3. 计算并填充 hash 值
"""
import sys
import os

# 确保能找到项目模块
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy import create_engine, text
from encryption_utils import encrypt, hash_for_lookup


def migrate():
    # 读取数据库连接
    from app_config import DATABASE_URL
    eng = create_engine(DATABASE_URL, pool_pre_ping=True)

    with eng.connect() as conn:
        # 0. 扩展 email/phone 字段长度以容纳加密数据
        print(">>> 扩展 email/phone 字段长度...")
        for col_type in ["email VARCHAR(200)", "phone VARCHAR(200)"]:
            col_name = col_type.split()[0]
            try:
                conn.execute(text(f"ALTER TABLE users MODIFY COLUMN {col_type}"))
                print(f"    列 {col_name} 已扩展")
            except Exception as e:
                print(f"    警告({col_name}): {e}")

        # 1. 添加新列（如果不存在）
        print(">>> 添加 email_hash / phone_hash 列...")
        for col in ["email_hash VARCHAR(64) UNIQUE", "phone_hash VARCHAR(64) UNIQUE"]:
            try:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {col}"))
                print(f"    列 {col.split()[0]} 已添加")
            except Exception as e:
                if "Duplicate column" in str(e):
                    print(f"    列已存在，跳过")
                else:
                    print(f"    警告: {e}")

        # 2. 查询所有有邮箱或手机号的用户
        rows = conn.execute(
            text("SELECT id, email, phone FROM users WHERE email IS NOT NULL OR phone IS NOT NULL")
        ).fetchall()
        print(f">>> 找到 {len(rows)} 个有联系方式待加密的用户")

        # 3. 逐个加密
        updated = 0
        for uid, email, phone in rows:
            enc_email = encrypt(email) if email else None
            enc_phone = encrypt(phone) if phone else None
            email_h = hash_for_lookup(email) if email else None
            phone_h = hash_for_lookup(phone) if phone else None

            conn.execute(
                text("UPDATE users SET email=:e, phone=:p, email_hash=:eh, phone_hash=:ph WHERE id=:id"),
                {"e": enc_email, "p": enc_phone, "eh": email_h, "ph": phone_h, "id": uid},
            )
            updated += 1
            if updated % 10 == 0:
                print(f"    已处理 {updated}/{len(rows)}...")

        conn.commit()

        # 4. 验证
        sample = conn.execute(
            text("SELECT id, email, phone, email_hash, phone_hash FROM users LIMIT 3")
        ).fetchall()
        print(f"\n>>> 迁移完成！已加密 {updated} 个用户")
        print("前 3 条样例（密文）:") if sample else None
        for s in sample:
            print(f"    ID={s[0]} email={s[1][:30] if s[1] else None} hash={s[3][:16] if s[3] else None}...")


if __name__ == "__main__":
    migrate()
