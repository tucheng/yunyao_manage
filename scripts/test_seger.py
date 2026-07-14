from sqlalchemy import text

from database import engine


with engine.connect() as conn:
    count = conn.execute(text("SELECT COUNT(1) FROM recipe_seger")).scalar_one()
    print(f"RecipeSeger rows: {count}")
    rows = conn.execute(text(
        "SELECT rs.recipe_id, r.title, rs.seger_unified, "
        "rs.acid_base_ratio, rs.acid_base_note "
        "FROM recipe_seger rs JOIN recipes r ON rs.recipe_id = r.id LIMIT 5"
    ))
    for row in rows:
        note = (row.acid_base_note or "")[:50]
        print(f"Recipe {row.recipe_id} ({row.title}): ratio={row.acid_base_ratio}, note={note}")
