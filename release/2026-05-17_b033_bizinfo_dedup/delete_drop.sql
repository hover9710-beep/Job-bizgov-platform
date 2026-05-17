-- b033 delete_drop — keeper 아닌 bizinfo 행 DELETE
-- 반드시 forward_merge.sql 직후 실행 (같은 세션 — bizinfo_keepers temp table 유지).
-- WHERE source='bizinfo' 강제. 다른 source 영향 0.

-- 안전 가드: bizinfo_keepers temp table 존재 검증
SELECT 'safety: bizinfo_keepers count' AS metric, COUNT(*) AS count FROM bizinfo_keepers;
SELECT 'safety: should be ~2740 (실 공고 수)' AS note;

-- 본 DELETE
DELETE FROM biz_projects
WHERE source = 'bizinfo'
  AND url LIKE '%pblancId=%'
  AND id NOT IN (SELECT keeper_id FROM bizinfo_keepers);

-- 검증
SELECT 'bizinfo after delete' AS metric, COUNT(*) AS count
FROM biz_projects WHERE source='bizinfo';

SELECT 'other sources (영향 0 검증)' AS metric, source, COUNT(*) AS count
FROM biz_projects WHERE source != 'bizinfo'
GROUP BY source ORDER BY count DESC;
