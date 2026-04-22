import sqlite3
conn = sqlite3.connect('db/biz.db')
conn.row_factory = sqlite3.Row
r = conn.execute('''
  SELECT id, title, source, receipt_start, receipt_end,
         start_date, end_date, description, url
  FROM biz_projects
  WHERE id = 516
''').fetchone()

print('receipt_start:', r['receipt_start'])
print('receipt_end  :', r['receipt_end'])
print('start_date   :', r['start_date'])
print('end_date     :', r['end_date'])
print('description  :', repr(str(r['description'] or '')[:200]))
print('url          :', r['url'])

Select-String -Path "pipeline\*.py" -Pattern "selectSIIA200Detail|description.*=|bizinfo.*detail" | Select-Object Filename, LineNumber, Line | Format-Table -AutoSize