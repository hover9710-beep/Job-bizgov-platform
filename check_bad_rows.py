import sqlite3

conn = sqlite3.connect("db/biz.db")
conn.row_factory = sqlite3.Row

rows = conn.execute("""
    SELECT id, title, organization, source, url
    FROM biz_projects
    WHERE source='jbexport'
      AND (url IS NULL OR TRIM(url)='')
    ORDER BY id
    LIMIT 50
""").fetchall()

for r in rows:
    print(dict(r))

print("총", len(rows), "건")