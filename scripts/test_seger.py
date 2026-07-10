import pymysql
conn = pymysql.connect(host='127.0.0.1', user='root', password='root', database='yunyao')
c = conn.cursor()
# Check if any recipe_seger data exists yet
c.execute("SELECT COUNT(*) FROM recipe_seger")
print(f"RecipeSeger rows: {c.fetchone()[0]}")
c.execute("SELECT rs.recipe_id, r.title, rs.seger_unified, rs.acid_base_ratio, rs.acid_base_note FROM recipe_seger rs JOIN recipes r ON rs.recipe_id = r.id LIMIT 5")
for row in c.fetchall():
    print(f"Recipe {row[0]} ({row[1]}): ratio={row[3]}, note={row[4][:50]}")
conn.close()
