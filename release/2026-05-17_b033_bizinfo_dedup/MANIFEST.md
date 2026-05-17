# b033 bizinfo 중복 제거 — 2026-05-17

## 배경

- bizinfo total: **15,625 행**
- unique pblancId: **2,740 개** (실 공고 수)
- 평균 중복 배수: **5.7배**
- 삭제 대상: **12,884 행 (82.5%)**

## keeper 결정 정책

같은 pblancId 그룹 내에서 다음 우선순위로 1행 선택:

1. `ai_friendly_title` NOT NULL AND TRIM != '' (통역 보존)
2. `created_at` DESC (최신 sync)
3. `id` DESC (tie-break)

## 보존 컬럼 (forward_merge)

keeper 가 NULL/empty 일 때 그룹 내 다른 row 의 NULL 아닌 값으로 채움 (사용자 결정 6 컬럼):

- `ai_friendly_title`
- `ai_friendly_summary`
- `ai_summary`
- `ai_summary_at`
- `description` (NULL/empty 아닌 것 우선)
- `attachments_json` (NULL/empty/`[]` 아닌 것 우선)

다른 컬럼 (view_count, recommend_label 등 운영 enrich) 은 dedup 후 별도 sync 시 운영 측에서 갱신.

## SQL 실행 순서

1. `validation_dry_run.sql` — 분포 + 영향 검증 (READ-ONLY)
2. `forward_merge.sql` — temp table `bizinfo_keepers` 생성 + 4 컬럼 보존 UPDATE
3. `delete_drop.sql` — keeper 아닌 행 DELETE
4. `cleanup_dead_references.sql` — click_log / favorite_projects / recommendations dead reference 정리

## 사고 시나리오 + 대응

| # | 시나리오 | 대응 |
|---|---|---|
| A | forward_merge 가 ai_friendly_* 손실 | 4 컬럼 명시 UPDATE, NULL 일 때만 채움 |
| B | 다른 source 영향 | 모든 SQL 에 `AND source='bizinfo'` 강제 |
| C | dead reference | Step 7 의 cleanup_dead_references.sql |
| D | crawler 재중복 INSERT | Step 2 의 connector 멱등성 fix 선행 필수 |
| E | 운영 DB 와 불일치 | Step 6 의 Render Shell 동일 SQL 실행 |

## ROLLBACK

```powershell
cp db/biz.db.backup_b033_pre_<timestamp> db/biz.db
py pipeline/sync_to_render.py
```

복구 시간: < 5분.

## 의존성

- Step 2 (crawler 멱등성) 가 Step 3-7 보다 선행 필수
- Step 6 (운영 sync) 는 Step 5 (v1 dedup) 후
- Step 7 (dead reference) 는 Step 5 후

## 검증 기대

| 항목 | 예상 |
|---|---|
| bizinfo total | 15,625 → ~2,740 (82% 감소) |
| ai_friendly_title NOT NULL | ~12,884 → ~2,365 (그룹별 1 보존) |
| 다른 source 영향 | 0 |
| 메인 페이지 count | 6,757 → ~1,500 |
| click_log/favorites 영향 | dead reference 정리 (수십 행 추정) |
