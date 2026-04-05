import sqlite3

conn = sqlite3.connect('db/biz.db')
cur = conn.cursor()

cur.execute("SELECT COUNT(*) FROM biz_projects WHERE ministry != ''")
print("ministry 채워진 행:", cur.fetchone()[0])

cur.execute("SELECT ministry, executing_agency FROM biz_projects WHERE ministry != '' LIMIT 5")
for r in cur.fetchall():
    print(r)

conn.close()