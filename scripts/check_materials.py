import pymysql
conn = pymysql.connect(host='127.0.0.1', user='root', password='root', database='yunyao')
c = conn.cursor()

# Check ceramic_materials structure
c.execute("SHOW CREATE TABLE ceramic_materials")
print("=== ceramic_materials DDL ===")
print(c.fetchone()[1])

print("\n=== Sample data ===")
c.execute("SELECT id, name, formula, molecular_weight, category FROM ceramic_materials LIMIT 30")
for row in c.fetchall():
    print(row)
print(f"\nTotal: {c.rowcount} rows")

# Check if there are oxide columns
c.execute("SHOW COLUMNS FROM ceramic_materials")
cols = [row[0] for row in c.fetchall()]
print(f"\nColumns: {cols}")

conn.close()
