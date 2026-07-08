"""迁移存量配料数据：加密 name/amount，计算 name_hash"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from security import encrypt, hash_for_lookup
import pymysql

conn = pymysql.connect(host='127.0.0.1', user='root', password='root', database='yunyao')
cur = conn.cursor()

# 1. 读取所有未加密的配料
cur.execute("SELECT id, name, amount FROM recipe_ingredients")
rows = cur.fetchall()
total = len(rows)
print(f"共 {total} 条配料需要加密")

# 2. 逐条加密
updated = 0
for row_id, name, amount in rows:
    enc_name = encrypt(name or "")
    enc_amount = encrypt(amount or "")
    name_h = hash_for_lookup(name or "")
    cur.execute(
        "UPDATE recipe_ingredients SET name=%s, amount=%s, name_hash=%s WHERE id=%s",
        (enc_name, enc_amount, name_h, row_id),
    )
    updated += 1
    if updated % 200 == 0:
        print(f"  已处理 {updated}/{total}")

conn.commit()
print(f"✅ 迁移完成：{updated} 条已加密")

# 3. 验证：取几条解密看看对不对
cur.execute("SELECT id, name, amount, name_hash FROM recipe_ingredients LIMIT 5")
for row_id, enc_name, enc_amount, name_h in cur.fetchall():
    from security import decrypt
    plain_name = decrypt(enc_name)
    plain_amount = decrypt(enc_amount)
    verify_hash = hash_for_lookup(plain_name)
    hash_ok = "✓" if verify_hash == name_h else "✗"
    print(f"   #{row_id}: {plain_name} = {plain_amount} | hash {hash_ok}")

cur.close()
conn.close()
print("✅ 迁移验证完成")
