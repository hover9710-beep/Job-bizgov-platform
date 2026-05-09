-- 백로그 047 + 048 후속 정정. Render Shell sqlite3 /var/data/biz.db 에서 실행.
-- url 매칭 (id 무관) — 운영/로컬 id 차이 안전.
-- 적용일: 2026-05-10

BEGIN;

-- ========== 백로그 047: 백필 4건 (selector 오작동으로 잘못 백필된 title 정정) ==========
UPDATE biz_projects SET title='[시장조사/지사화] [변경공고]2026년 전북특별자치도 해외통상거점센터 수출 실무 지원 서비스 참여기업 모집', start_date='2026-02-10', end_date='2026-11-30', status='진행', raw_status='접수중', period_text='2026-02-10 ~ 2026-11-30', biz_start='2026-02-10', biz_end='2026-11-30', receipt_start='2026-02-10', receipt_end='2026-11-30', updated_at=datetime('now') WHERE source='jbexport' AND url LIKE '%spSeq=4f3a1a39967a49148b031d6416e55614%';
UPDATE biz_projects SET title='[기타 지원사업] (중동 긴급) 2026 수출 물류비 지원사업', start_date='2026-04-13', end_date='2026-05-13', status='진행', raw_status='접수중', period_text='2026-04-13 ~ 2026-05-13', biz_start='2026-04-13', biz_end='2026-05-13', receipt_start='2026-04-13', receipt_end='2026-05-13', updated_at=datetime('now') WHERE source='jbexport' AND url LIKE '%spSeq=9fbace94ea0e48e4a2e7bcb9829f24a4%';
UPDATE biz_projects SET title='[온라인 마케팅] 2026년 미주/유럽/중동 언택트 마케팅 지원사업', start_date='2026-04-24', end_date='2026-12-31', status='진행', raw_status='접수중', period_text='2026-04-24 ~ 2026-12-31', biz_start='2026-04-24', biz_end='2026-12-31', receipt_start='2026-04-24', receipt_end='2026-12-31', updated_at=datetime('now') WHERE source='jbexport' AND url LIKE '%spSeq=9810ffef21cf4e869be5e38df525e408%';
UPDATE biz_projects SET title='[교육/컨설팅] 2026년 전북FTA통상진흥센터 설명회(미국 관세정책 및 보호무역 시대에 따른 한국 수출기업의 대응 전략과 수출 실무)', start_date='2026-05-08', end_date='2026-05-27', status='진행', raw_status='접수중', period_text='2026-05-08 ~ 2026-05-27', biz_start='2026-05-08', biz_end='2026-05-27', receipt_start='2026-05-08', receipt_end='2026-05-27', updated_at=datetime('now') WHERE source='jbexport' AND url LIKE '%spSeq=eb876dda1c7949f3b10e0e29685b5b43%';

-- ========== 백로그 048: status stale 4건 (사이트 접수마감 → DB 진행 정정) ==========
-- 전주시 AI 활용 디지털 마케팅
UPDATE biz_projects SET status='마감', raw_status='접수마감', updated_at=datetime('now') WHERE source='jbexport' AND url LIKE '%spSeq=8260a0d42d444760a0fd2428237c9393%';
-- 중국 시장 테스트 마케팅
UPDATE biz_projects SET status='마감', raw_status='접수마감', updated_at=datetime('now') WHERE source='jbexport' AND url LIKE '%spSeq=c02eb9e7bf2441f68603a890510b95a4%';
-- 서울푸드 연계 JB 바이어 상담회
UPDATE biz_projects SET status='마감', raw_status='접수마감', updated_at=datetime('now') WHERE source='jbexport' AND url LIKE '%spSeq=1d902514a6b4485795440bee26e22231%';
-- JB 해외 바이어 상담회
UPDATE biz_projects SET status='마감', raw_status='접수마감', updated_at=datetime('now') WHERE source='jbexport' AND url LIKE '%spSeq=8d9b66c907344f97a3efa214228e7722%';

-- ========== 신규 INSERT 2건 (사이트 #4 FTA 5차 교육, #12 KOTRA 설명회) ==========
-- 운영 DB에 동일 url 존재 시 skip (UNIQUE 제약 또는 ON CONFLICT 사용 권장)
INSERT INTO biz_projects (title, organization, start_date, end_date, status, url, source, raw_status, period_text, biz_start, biz_end, receipt_start, receipt_end, created_at, updated_at, collected_at, view_count) SELECT '[교육/컨설팅] 2026년 FTA통상진흥센터 5차 교육(수출 바이어 상담 및 협상 전략)', '(재)전북특별자치도 경제통상진흥원', '2026-04-27', '2026-05-04', '마감', 'https://www.jbexport.or.kr/other/spWork/spWorkSupportBusiness/detail1.do?menuUUID=402880867c8174de017c819251e70009&spSeq=93b55df14467448399e310540eab2e98', 'jbexport', '접수마감', '2026-04-27 ~ 2026-05-04', '2026-04-27', '2026-05-04', '2026-04-27', '2026-05-04', datetime('now'), datetime('now'), strftime('%Y-%m-%dT%H:%M:%SZ','now'), 0 WHERE NOT EXISTS (SELECT 1 FROM biz_projects WHERE url='https://www.jbexport.or.kr/other/spWork/spWorkSupportBusiness/detail1.do?menuUUID=402880867c8174de017c819251e70009&spSeq=93b55df14467448399e310540eab2e98');
INSERT INTO biz_projects (title, organization, start_date, end_date, status, url, source, raw_status, period_text, biz_start, biz_end, receipt_start, receipt_end, created_at, updated_at, collected_at, view_count) SELECT '[교육/컨설팅] 2026년 상반기 찾아가는 KOTRA 설명회 (4.15 / 전주)', '코트라 전북지원본부', '2026-04-10', '2026-04-14', '마감', 'https://www.jbexport.or.kr/other/spWork/spWorkSupportBusiness/detail1.do?menuUUID=402880867c8174de017c819251e70009&spSeq=20338576de7c4bdeb817ef63f2d8b3bd', 'jbexport', '접수마감', '2026-04-10 ~ 2026-04-14', '2026-04-10', '2026-04-14', '2026-04-10', '2026-04-14', datetime('now'), datetime('now'), strftime('%Y-%m-%dT%H:%M:%SZ','now'), 0 WHERE NOT EXISTS (SELECT 1 FROM biz_projects WHERE url='https://www.jbexport.or.kr/other/spWork/spWorkSupportBusiness/detail1.do?menuUUID=402880867c8174de017c819251e70009&spSeq=20338576de7c4bdeb817ef63f2d8b3bd');

COMMIT;

-- 검증:
-- SELECT id, status, raw_status, title FROM biz_projects
--   WHERE source='jbexport' AND id IN (해당 운영 id) ORDER BY id;