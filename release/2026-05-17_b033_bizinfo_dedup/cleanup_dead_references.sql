-- b033 dead reference cleanup
-- click_log / favorite_projects / recommendations 의 project_id 가
-- 살아남은 biz_projects.id 에 없는 행 DELETE.
-- 반드시 delete_drop.sql 후 실행.

-- click_log: project_id 가 TEXT 라 CAST 필요
SELECT 'click_log before' AS metric, COUNT(*) AS count FROM click_log;
DELETE FROM click_log
WHERE project_id IS NOT NULL
  AND CAST(project_id AS INTEGER) NOT IN (SELECT id FROM biz_projects);
SELECT 'click_log after' AS metric, COUNT(*) AS count FROM click_log;

-- favorite_projects: project_id TEXT
SELECT 'favorite_projects before' AS metric, COUNT(*) AS count FROM favorite_projects;
DELETE FROM favorite_projects
WHERE project_id IS NOT NULL
  AND CAST(project_id AS INTEGER) NOT IN (SELECT id FROM biz_projects);
SELECT 'favorite_projects after' AS metric, COUNT(*) AS count FROM favorite_projects;

-- recommendations: project_id INTEGER
SELECT 'recommendations before' AS metric, COUNT(*) AS count FROM recommendations;
DELETE FROM recommendations
WHERE project_id NOT IN (SELECT id FROM biz_projects);
SELECT 'recommendations after' AS metric, COUNT(*) AS count FROM recommendations;
