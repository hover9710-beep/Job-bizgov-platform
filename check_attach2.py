import sqlite3
import json

conn = sqlite3.connect('db/biz.db')
rows = conn.execute("""
    SELECT id, title, attachments_json
    FROM biz_projects
    WHERE source='jbexport'
      AND attachments_json IS NOT NULL
      AND TRIM(attachments_json) NOT IN ('', '[]')
    ORDER BY id
    LIMIT 10
""").fetchall()

print("조회 행수:", len(rows))
print("서로 다른 ID 수:", len(set(r[0] for r in rows)))
print("=" * 80)

for r in rows:
    pid = r[0]
    title = r[1]
    raw = r[2] or "[]"
    try:
        files = json.loads(raw)
    except Exception:
        files = []

    print(f"ID: {pid}")
    print(f"TITLE: {title}")
    print(f"첨부개수: {len(files)}")

    for f in files[:3]:
        print(" -", f.get("name"), "|", f.get("url"))

    if len(files) > 3:
        print(f" ... 외 {len(files)-3}개")

    print("-" * 80)

conn.close()