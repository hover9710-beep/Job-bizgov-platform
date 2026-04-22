import sqlite3

conn = sqlite3.connect('db/biz.db')
rows = conn.execute("""
SELECT id, title, attachments_json
FROM biz_projects
WHERE source='jbexport'
  AND attachments_json IS NOT NULL
  AND TRIM(attachments_json) NOT IN ('', '[]')
LIMIT 10
""").fetchall()

print("건수:", len(rows))
for r in rows:
    print("ID:", r[0])
    print("TITLE:", r[1])
    print("ATTACH:", r[2][:200])
    print("-" * 60)

conn.close()