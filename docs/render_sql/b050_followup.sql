-- 백로그 050 운영 적용 점검 SQL (Render Shell sqlite3 용)
-- 사전: backfill_organization.py 운영 실행 후 결과 검증.
-- 사고 위험 0 (SELECT only).

-- 1) jbexport organization 분포 — fallback 잔량 확인
SELECT
  COALESCE(organization, '(NULL)') AS organization,
  COUNT(*) AS n
FROM biz_projects
WHERE source = 'jbexport'
GROUP BY 1
ORDER BY 2 DESC;

-- 2) source='jbexport' url 도메인 검증 — 100% jbexport.or.kr 이어야 함
SELECT
  CASE
    WHEN url LIKE '%jbexport.or.kr%' THEN 'jbexport.or.kr'
    WHEN url IS NULL OR TRIM(url) = '' THEN '(no url)'
    ELSE '기타'
  END AS domain,
  COUNT(*) AS n
FROM biz_projects
WHERE source = 'jbexport'
GROUP BY 1 ORDER BY 2 DESC;

-- 3) 위젯 미리보기 (옵션 A 정책)
SELECT
  id,
  notice_chk AS chk,
  notice_order AS oder,
  substr(title, 1, 60) AS title,
  organization
FROM biz_projects
WHERE source = 'jbexport'
  AND COALESCE(TRIM(title), '') != ''
  AND title NOT LIKE 'spSeq=%'
  AND title NOT IN ('공고 상세보기', 'MENU')
  AND COALESCE(start_date, '') >= '2026-01-01'
ORDER BY
  COALESCE(notice_chk, 0) DESC,
  COALESCE(notice_order, 0) DESC,
  COALESCE(created_at, '') DESC,
  id DESC
LIMIT 5;

-- 4) fallback 잔량이 있을 때만 추가 백필 실행 안내
-- (결과 행 0 이면 정상)
SELECT COUNT(*) AS still_fallback
FROM biz_projects
WHERE source = 'jbexport'
  AND COALESCE(organization, '') = '전북수출통합지원시스템';
