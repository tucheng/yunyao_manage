import re
from database import SessionLocal
from models import Material, RecipeIngredient
from sqlalchemy import func
from collections import defaultdict

db = SessionLocal()

def norm(s):
    return re.sub(r'[\s\u3000\u00a0]+', '', s).lower() if s else ''

OXIDE_FIELDS = ['sio2','al2o3','fe2o3','tio2','cao','mgo','na2o','k2o',
                'zno','b2o3','p2o5','li2o','mno2','coo','sno2','cuo',
                'cr2o3','pbo','bao','sro','loi']

materials = db.query(Material).filter(Material.is_active == True).all()

# Group by exact (name, name_en)
groups = defaultdict(list)
for m in materials:
    key = (m.name, m.name_en or '')
    groups[key].append(m)

dups = {k: v for k, v in groups.items() if len(v) > 1}

print(f'同名组数: {len(dups)}')
print()

to_delete_total = []

for (name, name_en), items in sorted(dups.items(), key=lambda x: -len(x[1])):
    scored = []
    for m in items:
        oxide_count = sum(1 for f in OXIDE_FIELDS if getattr(m, f) is not None)
        recipe_count = db.query(func.count(RecipeIngredient.id)).filter(RecipeIngredient.material_id == m.id).scalar() or 0
        scored.append((m.id, oxide_count, recipe_count, m.name, m.name_en))
    
    # Sort: oxide count desc, recipe count desc, ID asc
    scored.sort(key=lambda x: (-x[1], -x[2], x[0]))
    
    keep = scored[0]
    to_delete = [s[0] for s in scored[1:]]
    to_delete_total.extend(to_delete)
    
    print(f'{keep[3]} / {keep[4]}: 保留 ID {keep[0]}({keep[1]}成分, {keep[2]}配方), 删除 {to_delete}')

print(f'\n总计: 保留 {len(dups)} 条, 删除 {len(to_delete_total)} 条')
print(f'删除ID: {sorted(to_delete_total)}')

# Check references
print('\n=== 引用检查 ===')
for mid in sorted(to_delete_total):
    rc = db.query(func.count(RecipeIngredient.id)).filter(RecipeIngredient.material_id == mid).scalar()
    if rc:
        print(f'  ID {mid}: 有 {rc} 个配方引用 ⚠️')

print('  全部无配方引用 ✅')
db.close()
