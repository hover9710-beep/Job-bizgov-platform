import sqlite3
import os

base = os.path.dirname(os.path.abspath(__file__))

for db_name in ['db/bizgov.db', 'db/biz.db']:
    path = os.path.join(base, db_name)
    try:
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='biz_projects'")
        if not cur.fetchone():
            print(f'{db_name}: biz_projects 테이블 없음')
            conn.close()
            continue

        cur.execute("SELECT COUNT(*) FROM biz_projects WHERE source='bizinfo'")
        total = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM biz_projects WHERE source='bizinfo' AND url LIKE '%cpage=%'")
        cpage_count = cur.fetchone()[0]

        cur.execute("""
            SELECT COUNT(*) FROM biz_projects
            WHERE source='bizinfo'
            AND (
                pblancId IS NULL
                OR pblancId=''
                OR url NOT LIKE '%' || pblancId || '%'
            )
        """)
        no_pblanc_count = cur.fetchone()[0]

        # 샘플 확인
        cur.execute("SELECT pblancId, url FROM biz_projects WHERE source='bizinfo' AND url LIKE '%cpage=%' LIMIT 3")
        samples = cur.fetchall()

        print(f'{db_name}:')
        print(f'  bizinfo 전체: {total}')
        print(f'  cpage= 포함: {cpage_count}')
        print(f'  pblancId가 url에 없는 행: {no_pblanc_count}')
        if samples:
            print('  [cpage= 샘플]')
            for s in samples:
                print(f'    pblancId={s[0]}, url={s[1][:80]}')
        conn.close()
    except Exception as e:
        print(f'{db_name} 오류: {e}')
