import sqlite3
c=sqlite3.connect('db/biz.db')
c.execute("UPDATE biz_projects SET source='kstartup' WHERE source='unknown'")
print('done:',c.total_changes)
c.commit()