#!/usr/bin/env python
"""Find AK Flux records in glazy_materials"""
import re
import pymysql

with open('.env', 'r') as f:
    content = f.read()

url_line = [l for l in content.split('\n') if l.startswith('DATABASE_URL=')][0]
url = url_line.split('=', 1)[1].strip()

# Parse mysql+pymysql://user:pass@host:port/db
m = re.match(r'mysql\+pymysql://([^:]+):([^@]+)@([^:]+):(\d+)/([^?]+)', url)
if not m:
    print("Failed to parse DB URL")
    exit(1)

user, password, host, port, db = m.groups()

conn = pymysql.connect(host=host, user=user, password=password, database=db, port=int(port))
cur = conn.cursor()

# Search for AK Flux, AKF, akw related
cur.execute("""
    SELECT id, name, name_cn FROM glazy_materials 
    WHERE name LIKE '%AK Flux%' 
       OR name LIKE '%akw%' 
       OR name LIKE '%AKW%'
       OR name LIKE '%AKF%'
       OR name LIKE '%ak flux%'
       OR name LIKE '%alkali flux%'
       OR name LIKE '%Alkali Flux%'
""")
rows = cur.fetchall()
print("Found {} records:".format(len(rows)))
for r in rows:
    print("ID={} | name='{}' | name_cn='{}'".format(r[0], r[1], r[2]))

conn.close()
