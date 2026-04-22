import sqlite3
c=sqlite3.connect('db/biz.db')
c.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_url ON biz_projects(url)')
c.commit()
print('done')