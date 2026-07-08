#!/usr/bin/env python3
# migrate_db.py - Database migration for yunyao
import pymysql, re

MW = {"SiO2":60.08,"Al2O3":101.96,"Fe2O3":159.69,"TiO2":79.87,"CaO":56.08,"MgO":40.30,"Na2O":61.98,"K2O":94.20,"ZnO":81.38,"B2O3":69.62,"P2O5":141.94,"H2O":18.015}
CM = {"SIO2":"sio2","AL2O3":"al2o3","FE2O3":"fe2o3","TIO2":"tio2","CAO":"cao","MGO":"mgo","NA2O":"na2o","K2O":"k2o","ZNO":"zno","B2O3":"b2o3","P2O5":"p2o5","H2O":"loi"}
OX = ["sio2","al2o3","fe2o3","tio2","cao","mgo","na2o","k2o","zno","b2o3","p2o5","loi"]

def fa(f):
    r=[]
    for c in f:
        o=ord(c)
        if 0x2080<=o<=0x2089: r.append(str(o-0x2080))
        elif c in chr(0xB7)+chr(0x30FB): r.append(".")
        else: r.append(c)
    return "".join(r)

def cc(formula):
    if not formula or not formula.strip(): return {}
    f=fa(formula)
    ps=[p.strip() for p in f.split(".") if p.strip()]
    if not ps: return {}
    if len(ps)==1:
        p=ps[0]
        m=re.match(r'^(\d+\.?\d*)?(.+)$',p)
        if m:
            inn=m.group(2).strip()
            for on in ["SiO2","Al2O3","Fe2O3","TiO2","CaO","MgO","Na2O","K2O","ZnO","B2O3","P2O5","H2O"]:
                if inn.upper()==on.upper():
                    col=CM.get(on.upper())
                    if col: return {col:99.0}
    comp={}; tmw=0.0
    for pt in ps:
        m=re.match(r'^(\d+\.?\d*)?(.+)$',pt)
        if m:
            cs=m.group(1); ox=m.group(2).strip(); cnt=float(cs) if cs else 1.0
            for k,v in MW.items():
                if k.upper()==ox.upper(): tmw+=cnt*v; comp[k.upper()]=comp.get(k.upper(),0.0)+cnt*v; break
    if tmw==0: return {}
    res={}
    for ou,wt in comp.items():
        col=CM.get(ou)
        if col: res[col]=round(wt/tmw*100,2)
    return res

KWN={
    "苏州土":{"sio2":46.5,"al2o3":38.5,"fe2o3":0.3,"tio2":0.1,"cao":0.1,"mgo":0.1,"na2o":0.1,"k2o":0.1,"loi":14.0},
    "膨润土":{"sio2":65.0,"al2o3":18.0,"fe2o3":2.5,"tio2":0.3,"cao":2.0,"mgo":3.0,"na2o":2.5,"k2o":0.5,"loi":6.0},
    "滑石":{"sio2":62.0,"mgo":31.0,"al2o3":0.5,"fe2o3":0.2,"cao":0.5,"loi":5.5},
    "滑石粉":{"sio2":62.0,"mgo":31.0,"al2o3":0.5,"fe2o3":0.2,"cao":0.5,"loi":5.5},
    "白云石":{"cao":30.0,"mgo":21.0,"sio2":1.0,"fe2o3":0.1,"al2o3":0.3,"loi":47.0},
    "石灰石":{"cao":55.0,"mgo":0.5,"sio2":1.0,"fe2o3":0.2,"al2o3":0.3,"loi":43.0},
    "方解石":{"cao":56.0,"sio2":0.1,"fe2o3":0.1,"loi":43.5},
    "碳酸钙":{"cao":56.0,"loi":44.0},
    "钾长石":{"sio2":64.8,"al2o3":18.3,"k2o":16.9,"fe2o3":0.1,"na2o":0.5,"loi":0.3},
    "钠长石":{"sio2":68.0,"al2o3":19.0,"na2o":11.5,"k2o":0.5,"fe2o3":0.1,"cao":0.3,"loi":0.3},
    "长石":{"sio2":65.0,"al2o3":18.0,"k2o":12.0,"na2o":3.0,"fe2o3":0.1,"cao":0.5,"loi":0.5},
    "高岭土":{"sio2":46.5,"al2o3":39.5,"fe2o3":0.3,"tio2":0.1,"loi":13.9},
    "墇青石":{"sio2":51.0,"al2o3":34.0,"mgo":14.0,"loi":0.5},
    "硅灰石":{"sio2":51.0,"cao":47.0,"fe2o3":0.2,"loi":1.0},
    "透辉石":{"sio2":55.0,"cao":25.0,"mgo":18.0,"fe2o3":1.0,"al2o3":1.0},
    "叶蜡石":{"sio2":65.0,"al2o3":28.0,"fe2o3":0.3,"tio2":0.2,"loi":5.0},
    "伊利石":{"sio2":55.0,"al2o3":28.0,"fe2o3":1.5,"tio2":0.5,"cao":0.5,"mgo":1.5,"na2o":0.5,"k2o":5.0,"loi":7.0},
    "绿泥石":{"sio2":35.0,"al2o3":20.0,"fe2o3":2.0,"mgo":30.0,"loi":10.0},
    "蛇纹石":{"sio2":44.0,"mgo":43.0,"fe2o3":0.5,"al2o3":0.5,"loi":12.0},
    "菱镁矿":{"mgo":47.0,"loi":52.0},
    "碳酸镁":{"mgo":47.0,"loi":52.0},
    "磷酸钙":{"cao":54.0,"p2o5":45.0,"loi":1.0},
    "骨灰":{"cao":54.0,"p2o5":42.0,"loi":3.0},
    "硡酸":{"b2o3":56.0,"loi":44.0},
    "硡砂":{"na2o":16.0,"b2o3":36.0,"loi":47.0},
    "石英":{"sio2":99.0},
    "硅石":{"sio2":99.0},
    "刚玉":{"al2o3":99.0},
    "氧化锌":{"zno":99.0},
    "氧化铝":{"al2o3":99.0},
    "氧化铁":{"fe2o3":99.0},
    "氧化钛":{"tio2":99.0},
    "氧化镁":{"mgo":99.0},
    "氧化钙":{"cao":99.0},
    "碳化硅":{"sio2":0.5},
    "锆英石":{"sio2":33.0},
    "硅酸锆":{"sio2":33.0},
    "碳酸钠":{"na2o":58.5,"loi":41.5},
    "碳酸钾":{"k2o":68.0,"loi":32.0},
}

def gk(name):
    for k,v in KWN.items():
        if k in name: return v
    return None

conn = pymysql.connect(host="127.0.0.1",user="root",password="root",database="yunyao",charset="utf8mb4",cursorclass=pymysql.cursors.DictCursor)
cur = conn.cursor()

# Step 1: ALTER TABLE
print("=== Step 1: ALTER TABLE ceramic_materials ===")
try:
    cur.execute("ALTER TABLE ceramic_materials ADD COLUMN name_en VARCHAR(100) DEFAULT '' AFTER name")
    cur.execute("ALTER TABLE ceramic_materials ADD COLUMN sio2 FLOAT DEFAULT NULL AFTER molecular_weight")
    cur.execute("ALTER TABLE ceramic_materials ADD COLUMN al2o3 FLOAT DEFAULT NULL AFTER sio2")
    cur.execute("ALTER TABLE ceramic_materials ADD COLUMN fe2o3 FLOAT DEFAULT NULL AFTER al2o3")
    cur.execute("ALTER TABLE ceramic_materials ADD COLUMN tio2 FLOAT DEFAULT NULL AFTER fe2o3")
    cur.execute("ALTER TABLE ceramic_materials ADD COLUMN cao FLOAT DEFAULT NULL AFTER tio2")
    cur.execute("ALTER TABLE ceramic_materials ADD COLUMN mgo FLOAT DEFAULT NULL AFTER cao")
    cur.execute("ALTER TABLE ceramic_materials ADD COLUMN na2o FLOAT DEFAULT NULL AFTER mgo")
    cur.execute("ALTER TABLE ceramic_materials ADD COLUMN k2o FLOAT DEFAULT NULL AFTER na2o")
    cur.execute("ALTER TABLE ceramic_materials ADD COLUMN zno FLOAT DEFAULT NULL AFTER k2o")
    cur.execute("ALTER TABLE ceramic_materials ADD COLUMN b2o3 FLOAT DEFAULT NULL AFTER zno")
    cur.execute("ALTER TABLE ceramic_materials ADD COLUMN p2o5 FLOAT DEFAULT NULL AFTER b2o3")
    cur.execute("ALTER TABLE ceramic_materials ADD COLUMN loi FLOAT DEFAULT NULL AFTER p2o5")
    conn.commit()
    print("  OK")
except Exception as e:
    conn.rollback()
    if "Duplicate" in str(e):
        print("  Some columns already exist - OK")
    else:
        print(f"  Error: {e}")

# Step 2: CREATE TABLE
print()
print("=== Step 2: CREATE TABLE recipe_seger ===")
try:
    cur.execute('''CREATE TABLE IF NOT EXISTS recipe_seger (
        id INT AUTO_INCREMENT PRIMARY KEY,
        recipe_id INT NOT NULL UNIQUE,
        seger_unified VARCHAR(500) DEFAULT '',
        seger_al2o3 FLOAT DEFAULT NULL,
        seger_sio2 FLOAT DEFAULT NULL,
        seger_ro FLOAT DEFAULT NULL,
        acid_base_ratio FLOAT DEFAULT NULL,
        acid_base_note VARCHAR(500) DEFAULT '',
        seger_detail TEXT DEFAULT NULL,
        calculated_at DATETIME DEFAULT NULL,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX ix_recipe_seger_recipe_id (recipe_id),
        FOREIGN KEY (recipe_id) REFERENCES recipes(id)
    )''')
    conn.commit()
    print("  OK")
except Exception as e:
    if "already exists" in str(e).lower():
        print("  Already exists - OK")
        conn.rollback()
    else:
        print(f"  Error: {e}")
        conn.rollback()

# Step 3: Populate oxide data
print()
print("=== Step 3: Populating oxide data ===")
cur.execute("SELECT id,name,formula FROM ceramic_materials ORDER BY id")
rows=cur.fetchall()
print(f"  Found {len(rows)} rows")
uc=0
for r in rows:
    mid,name,formula=r['id'],r['name'],r['formula']
    comp=cc(formula)
    if not comp: comp=gk(name)
    if not comp:
        print(f"  WARNING: No comp id={mid} name={name}")
        continue
    sp=[f'{c}={comp[c]}' for c in OX if c in comp]
    if sp:
        cur.execute(f'UPDATE ceramic_materials SET {", ".join(sp)} WHERE id={mid}')
        uc+=1
        cs=', '.join(f'{k}={v}' for k,v in comp.items() if v)
        print(f"  id={mid:3d} ({name:10s}): {cs}")
conn.commit()

# Verification
print()
print('=== Verification ===')
print(f"  Rows updated: {uc}")
w=' OR '.join(f'{c} IS NOT NULL' for c in OX)
cur.execute(f'SELECT COUNT(*) as cnt FROM ceramic_materials WHERE {w}')
print(f"  Rows with oxide data: {cur.fetchone()['cnt']}")
cur.execute('SELECT id,name,sio2,al2o3,fe2o3,cao,mgo,na2o,k2o,loi FROM ceramic_materials WHERE sio2 IS NOT NULL OR al2o3 IS NOT NULL ORDER BY id LIMIT 10')
print('  Samples:')
for s in cur.fetchall():
    vals={k:v for k,v in s.items() if v is not None and k not in ('id','name')}
    print(f'    id={s["id"]:3d} {s["name"]:10s} -> {vals}')
conn.close()
print()
print('Migration complete!')
