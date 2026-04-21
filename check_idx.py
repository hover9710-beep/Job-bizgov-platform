import sqlite3
c = sqlite3.connect('db/biz.db')
idx = c.execute('SELECT name FROM sqlite_master WHERE type=chr(39)+chr(105)+chr(110)+chr(100)+chr(101)+chr(120) AND tbl_name=chr(39)+chr(98)+chr(105)+chr(122)').fetchall()
c2 = sqlite3.connect('db/biz.db')
idx2 = c2.execute('PRAGMA index_list(biz_projects)').fetchall()
for i in idx2: print(i)
c2.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_url ON biz_projects(url)')
c2.commit()
print('idx_url 생성 완료')
