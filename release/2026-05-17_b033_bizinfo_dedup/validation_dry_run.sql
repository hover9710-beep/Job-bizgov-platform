-- b033 DRY-RUN 검증 (READ-ONLY)
-- 모든 SELECT 만. DB 변경 X.

.print '=== 1) bizinfo 현재 분포 ==='
SELECT 'bizinfo total' AS metric, COUNT(*) AS count
FROM biz_projects WHERE source='bizinfo';

SELECT 'pblancId URL 보유' AS metric, COUNT(*) AS count
FROM biz_projects WHERE source='bizinfo' AND url LIKE '%pblancId=%';

SELECT 'unique pblancId' AS metric,
       COUNT(DISTINCT SUBSTR(url, INSTR(url, 'pblancId=')+9, 20)) AS count
FROM biz_projects WHERE source='bizinfo' AND url LIKE '%pblancId=%';

.print ''
.print '=== 2) 삭제 대상 추정 ==='
WITH cnt AS (
    SELECT COUNT(*) AS total,
           COUNT(DISTINCT SUBSTR(url, INSTR(url, 'pblancId=')+9, 20)) AS uniq
    FROM biz_projects WHERE source='bizinfo' AND url LIKE '%pblancId=%'
)
SELECT 'delete target' AS metric, (total - uniq) AS count FROM cnt;

.print ''
.print '=== 3) keeper 시뮬 (rn=1 행 5개 샘플) ==='
WITH ranked AS (
    SELECT
        id,
        SUBSTR(url, INSTR(url, 'pblancId=')+9, 20) AS pid,
        ai_friendly_title,
        created_at,
        ROW_NUMBER() OVER (
            PARTITION BY SUBSTR(url, INSTR(url, 'pblancId=')+9, 20)
            ORDER BY
                CASE WHEN ai_friendly_title IS NOT NULL AND TRIM(ai_friendly_title) != '' THEN 0 ELSE 1 END,
                COALESCE(created_at, '') DESC,
                id DESC
        ) AS rn
    FROM biz_projects
    WHERE source='bizinfo' AND url LIKE '%pblancId=%'
)
SELECT id, pid, ai_friendly_title, created_at FROM ranked WHERE rn=1 LIMIT 5;

.print ''
.print '=== 4) 통역 손실 추정 (forward_merge 적용 가정) ==='
-- 동일 pid 그룹 중 keeper 가 ai_friendly_title NULL 이고, 그룹 내 다른 row 에 NOT NULL 있는 그룹
-- → forward_merge 가 채울 대상
WITH ranked AS (
    SELECT id, SUBSTR(url, INSTR(url, 'pblancId=')+9, 20) AS pid, ai_friendly_title,
        ROW_NUMBER() OVER (
            PARTITION BY SUBSTR(url, INSTR(url, 'pblancId=')+9, 20)
            ORDER BY
                CASE WHEN ai_friendly_title IS NOT NULL AND TRIM(ai_friendly_title) != '' THEN 0 ELSE 1 END,
                COALESCE(created_at, '') DESC, id DESC
        ) AS rn
    FROM biz_projects WHERE source='bizinfo' AND url LIKE '%pblancId=%'
)
SELECT 'keeper 이미 통역 OK' AS metric, COUNT(*) AS count
FROM ranked
WHERE rn=1 AND ai_friendly_title IS NOT NULL AND TRIM(ai_friendly_title) != '';

.print ''
.print '=== 5) 다른 source 영향 0 검증 ==='
SELECT source, COUNT(*) AS count FROM biz_projects WHERE source != 'bizinfo' GROUP BY source ORDER BY count DESC;
