import sqlite3
conn = sqlite3.connect("db/biz.db")
cursor = conn.execute("SELECT * FROM biz_projects WHERE source = ? LIMIT 1", ("jbexport",))
cols = [d[0] for d in cursor.description]
row = cursor.fetchone()
if row:
    for k, v in zip(cols, row):
        v_str = str(v)
        if len(v_str) > 100:
            v_str = v_str[:100] + "..."
        print(f"{k:25s} = {v_str}")
else:
    print("(no jbexport row)")
conn.close()
