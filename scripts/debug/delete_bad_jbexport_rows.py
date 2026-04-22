import sqlite3

conn = sqlite3.connect("db/biz.db")

cur = conn.execute("""
    DELETE FROM biz_projects
    WHERE source='jbexport'
      AND (url IS NULL OR TRIM(url)='')
""")

conn.commit()
print("삭제 건수:", cur.rowcount)