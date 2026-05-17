-- b033 forward_merge — keeper 결정 + 4 컬럼 보존 UPDATE
-- WHERE source='bizinfo' 강제. 다른 source 영향 0.
-- 실행 전 backup 필수 (db/biz.db.backup_b033_pre_*).

-- 1) keeper 결정 (temp table)
DROP TABLE IF EXISTS bizinfo_keepers;
CREATE TEMP TABLE bizinfo_keepers AS
WITH ranked AS (
    SELECT
        id,
        SUBSTR(url, INSTR(url, 'pblancId=')+9, 20) AS pid,
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
SELECT id AS keeper_id, pid FROM ranked WHERE rn = 1;

CREATE INDEX IF NOT EXISTS idx_bizinfo_keepers_pid ON bizinfo_keepers(pid);
CREATE INDEX IF NOT EXISTS idx_bizinfo_keepers_id ON bizinfo_keepers(keeper_id);

-- 2) 4 컬럼 forward_merge (keeper 의 NULL 컬럼만 채움)

-- 2a) ai_friendly_title
UPDATE biz_projects
SET ai_friendly_title = (
    SELECT bp.ai_friendly_title
    FROM biz_projects bp
    JOIN bizinfo_keepers k
      ON SUBSTR(bp.url, INSTR(bp.url, 'pblancId=')+9, 20) = k.pid
    WHERE k.keeper_id = biz_projects.id
      AND bp.source='bizinfo'
      AND bp.id != biz_projects.id
      AND bp.ai_friendly_title IS NOT NULL
      AND TRIM(bp.ai_friendly_title) != ''
    ORDER BY COALESCE(bp.created_at, '') DESC, bp.id DESC
    LIMIT 1
)
WHERE id IN (SELECT keeper_id FROM bizinfo_keepers)
  AND (ai_friendly_title IS NULL OR TRIM(ai_friendly_title) = '');

-- 2b) ai_friendly_summary
UPDATE biz_projects
SET ai_friendly_summary = (
    SELECT bp.ai_friendly_summary
    FROM biz_projects bp
    JOIN bizinfo_keepers k
      ON SUBSTR(bp.url, INSTR(bp.url, 'pblancId=')+9, 20) = k.pid
    WHERE k.keeper_id = biz_projects.id
      AND bp.source='bizinfo'
      AND bp.id != biz_projects.id
      AND bp.ai_friendly_summary IS NOT NULL
      AND TRIM(bp.ai_friendly_summary) != ''
    ORDER BY COALESCE(bp.created_at, '') DESC, bp.id DESC
    LIMIT 1
)
WHERE id IN (SELECT keeper_id FROM bizinfo_keepers)
  AND (ai_friendly_summary IS NULL OR TRIM(ai_friendly_summary) = '');

-- 2c) ai_summary
UPDATE biz_projects
SET ai_summary = (
    SELECT bp.ai_summary
    FROM biz_projects bp
    JOIN bizinfo_keepers k
      ON SUBSTR(bp.url, INSTR(bp.url, 'pblancId=')+9, 20) = k.pid
    WHERE k.keeper_id = biz_projects.id
      AND bp.source='bizinfo'
      AND bp.id != biz_projects.id
      AND bp.ai_summary IS NOT NULL
      AND TRIM(bp.ai_summary) != ''
    ORDER BY COALESCE(bp.created_at, '') DESC, bp.id DESC
    LIMIT 1
)
WHERE id IN (SELECT keeper_id FROM bizinfo_keepers)
  AND (ai_summary IS NULL OR TRIM(ai_summary) = '');

-- 2d) ai_summary_at
UPDATE biz_projects
SET ai_summary_at = (
    SELECT bp.ai_summary_at
    FROM biz_projects bp
    JOIN bizinfo_keepers k
      ON SUBSTR(bp.url, INSTR(bp.url, 'pblancId=')+9, 20) = k.pid
    WHERE k.keeper_id = biz_projects.id
      AND bp.source='bizinfo'
      AND bp.id != biz_projects.id
      AND bp.ai_summary_at IS NOT NULL
      AND TRIM(bp.ai_summary_at) != ''
    ORDER BY COALESCE(bp.created_at, '') DESC, bp.id DESC
    LIMIT 1
)
WHERE id IN (SELECT keeper_id FROM bizinfo_keepers)
  AND (ai_summary_at IS NULL OR TRIM(ai_summary_at) = '');

-- 2e) description
UPDATE biz_projects
SET description = (
    SELECT bp.description
    FROM biz_projects bp
    JOIN bizinfo_keepers k
      ON SUBSTR(bp.url, INSTR(bp.url, 'pblancId=')+9, 20) = k.pid
    WHERE k.keeper_id = biz_projects.id
      AND bp.source='bizinfo'
      AND bp.id != biz_projects.id
      AND bp.description IS NOT NULL
      AND TRIM(bp.description) != ''
    ORDER BY COALESCE(bp.created_at, '') DESC, bp.id DESC
    LIMIT 1
)
WHERE id IN (SELECT keeper_id FROM bizinfo_keepers)
  AND (description IS NULL OR TRIM(description) = '');

-- 2f) attachments_json
UPDATE biz_projects
SET attachments_json = (
    SELECT bp.attachments_json
    FROM biz_projects bp
    JOIN bizinfo_keepers k
      ON SUBSTR(bp.url, INSTR(bp.url, 'pblancId=')+9, 20) = k.pid
    WHERE k.keeper_id = biz_projects.id
      AND bp.source='bizinfo'
      AND bp.id != biz_projects.id
      AND bp.attachments_json IS NOT NULL
      AND TRIM(bp.attachments_json) != ''
      AND bp.attachments_json != '[]'
    ORDER BY COALESCE(bp.created_at, '') DESC, bp.id DESC
    LIMIT 1
)
WHERE id IN (SELECT keeper_id FROM bizinfo_keepers)
  AND (attachments_json IS NULL OR TRIM(attachments_json) = '' OR attachments_json = '[]');

-- 검증
SELECT 'keepers count' AS metric, COUNT(*) AS count FROM bizinfo_keepers;
SELECT 'keepers with ai_friendly_title' AS metric, COUNT(*) AS count
FROM biz_projects
WHERE id IN (SELECT keeper_id FROM bizinfo_keepers)
  AND ai_friendly_title IS NOT NULL AND TRIM(ai_friendly_title) != '';
