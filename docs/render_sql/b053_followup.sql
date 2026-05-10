-- 백로그 053 follow-up SQL (jbtp 위젯 정렬 + start_date)
-- Render Shell 또는 sqlite3 db/biz.db 에서 실행 (점검용 — 변경 없음)

-- ===========================================================
-- 1) 백필 BEFORE/AFTER 분포 점검
-- ===========================================================

-- 전체 jbtp row 수
SELECT 'total' AS metric, COUNT(*) AS cnt FROM biz_projects WHERE source='jbtp';

-- notice_chk 분포
SELECT 'notice_chk' AS metric, notice_chk, COUNT(*) AS cnt
FROM biz_projects WHERE source='jbtp'
GROUP BY notice_chk ORDER BY notice_chk DESC;

-- start_date 채워짐 비율
SELECT
    SUM(CASE WHEN COALESCE(start_date,'')!='' THEN 1 ELSE 0 END) AS sd_filled,
    SUM(CASE WHEN COALESCE(start_date,'')>='2026-01-01' THEN 1 ELSE 0 END) AS sd_2026,
    COUNT(*) AS total
FROM biz_projects WHERE source='jbtp';

-- ===========================================================
-- 2) 위젯 시뮬 — 공지 제외 top 5 (백로그 053 정책)
-- ===========================================================

SELECT id, notice_chk, notice_order, start_date, substr(title, 1, 60) AS title_head
FROM biz_projects
WHERE source='jbtp'
  AND COALESCE(notice_chk, 0) = 0
  AND COALESCE(start_date, '') >= '2026-01-01'
ORDER BY COALESCE(notice_order, 0) DESC,
         COALESCE(created_at, '') DESC, id DESC
LIMIT 5;

-- ===========================================================
-- 3) 사이트와 매칭 검증 — dataSid 매칭 패턴
-- ===========================================================

-- 위젯 5건의 url 에서 dataSid 추출 (검증용)
-- 사이트 page1 일반글 1~5위 dataSid: 20137 / 20129 / 20152 / 20151 / 20145 (2026-05-10 시점)
SELECT id, notice_order AS seq, url, substr(title, 1, 50) AS title_head
FROM biz_projects
WHERE source='jbtp'
  AND COALESCE(notice_chk, 0) = 0
  AND url LIKE '%dataSid=20137%' UNION
SELECT id, notice_order AS seq, url, substr(title, 1, 50) AS title_head
FROM biz_projects
WHERE source='jbtp' AND url LIKE '%dataSid=20129%' UNION
SELECT id, notice_order AS seq, url, substr(title, 1, 50) AS title_head
FROM biz_projects
WHERE source='jbtp' AND url LIKE '%dataSid=20152%' UNION
SELECT id, notice_order AS seq, url, substr(title, 1, 50) AS title_head
FROM biz_projects
WHERE source='jbtp' AND url LIKE '%dataSid=20151%' UNION
SELECT id, notice_order AS seq, url, substr(title, 1, 50) AS title_head
FROM biz_projects
WHERE source='jbtp' AND url LIKE '%dataSid=20145%';

-- ===========================================================
-- 4) 백필 누락 row 진단 (no_match)
-- ===========================================================

-- url 에 dataSid 없는 row (잘못된 형식, 정상 0 예상)
SELECT id, url FROM biz_projects
WHERE source='jbtp' AND url NOT LIKE '%dataSid=%';

-- start_date 미채움 row (9페이지 이후 옛 row, 정상)
SELECT id, url, title FROM biz_projects
WHERE source='jbtp' AND COALESCE(start_date,'')=''
ORDER BY id DESC LIMIT 10;
