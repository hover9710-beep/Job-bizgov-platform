import sqlite3
c=sqlite3.connect('db/biz.db')
c.execute('DELETE FROM biz_projects WHERE id NOT IN (SELECT MIN(id) FROM biz_projects GROUP BY url)')
print('중복삭제:',c.total_changes)
c.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_url ON biz_projects(url)')
c.commit()
print('done')