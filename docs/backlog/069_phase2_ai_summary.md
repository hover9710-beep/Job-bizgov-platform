# 백로그 069 — Phase 2 AI 한줄요약 완비 (`ai_summary` backfill + Actions step + sync)

> **상태**: 2026-05-17 EOD — 본 작업 완료 (widget coverage 100%, 운영 sync OK)
> **선행 의존**: b065 (Actions sync 인프라), b066 (batch 패턴), b067 (ai_translate Actions step), b033 (bizinfo dedup → 비용 5배 절감)
> **사이클 분리**: 본 사이클 = Phase 2 (`ai_summary` 만). Phase 3 (첨부 분석) / Phase 4 (맞춤 추천) 별도.

---

## 작업 정의

`biz_projects.ai_summary` 컬럼 — 위젯 노출 대상 (`start_date >= 2026-01-01`) 의 한줄 요약을 자동 + backfill 로 100% 채움.

### 범위

| 항목 | 정책 |
|---|---|
| backfill 대상 | widget (`start_date >= 2026-01-01`) 만 (전체 3,697 row 중 widget 1,641) |
| 일일 자동화 | `daily-crawl.yml` 의 `ai-summary` step (`--widget-targets --limit 200`) |
| 모델 | `gpt-4o-mini` (max_tokens=100, temperature=0.3, prompt 50자 이내) |
| 입력 우선순위 | `attachment_text` → `description` → `title+organization` (실측: 99.9% title+org fallback) |
| 멱등성 | `WHERE ai_summary IS NULL` (overwrite 옵션 별도) |

---

## 구현

### 1. 모듈 (선행 commit `dc181fc` ~ `5b87ef0` 에 포함)

- `pipeline/ai_summary.py` — `generate_project_summary(item, text)` (gpt-4o-mini)
- `pipeline/ai_summary_cache.py` — batch (BATCH_SIZE=10) + chunked commit (COMMIT_INTERVAL=50)
  - mode 1: 기본 (mail 후보)
  - mode 2: `--source/--status/--end-date-from` (필터 backfill)
  - mode 3: `--widget-targets` (위젯 노출 대상, b069 신설)

### 2. Actions step (선행 commit `9521634` 에 포함)

`.github/workflows/daily-crawl.yml`:

```yaml
- name: AI summary (non-fatal)
  id: ai-summary
  if: always()
  continue-on-error: true
  timeout-minutes: 10
  env:
    OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
  run: |
    python -m pipeline.ai_summary_cache --widget-targets --limit 200
```

- summary step 의 outcome 검사 대상 (`O_AISUMMARY`), critical 분류 X (WARN only)
- `continue-on-error: true` → sync 단계 진행 보장
- timeout 10분 — 200건 batch 처리 여유

### 3. Sync whitelist

`pipeline/sync_to_render.py` 의 `SYNC_FIELDS` + `appy.py` 의 `SYNC_UPDATE_WHITELIST` 모두 `ai_summary`, `ai_summary_at` 포함 (양쪽 동기화).

### 4. Sync flag reset 정책 (사후 발견)

⚠️ `ai_summary_cache.py` 의 UPDATE 는 `synced_to_render` flag 를 reset 하지 않음.

→ backfill 후 운영 반영을 위해서는 수동 reset 필요:

```sql
UPDATE biz_projects
SET synced_to_render = 0
WHERE ai_summary_at >= '<backfill_date>'
  AND ai_summary IS NOT NULL AND ai_summary != ''
```

→ 다음 사이클에서 `ai_summary_cache.py` 의 UPDATE 에 `synced_to_render = 0` 추가하는 patch 권장 (Phase 2.1 fix).

---

## 2026-05-17 EOD 진행 기록

### 시뮬 (사전)

- `docs/simulations/2026-05-17_phase2_ai_summary.md` — 9단계 + 5보완 영향 분석
- 결정 사항 6건 명세 → 사용자 옵션 C (5/17 EOD 즉시 진행) 채택

### 실행 (Step 7~9)

| Step | 작업 | 결과 |
|---|---|---|
| 7 | 백업 + dry-run + backfill | `pending=1` (선행 cron 이 1640 처리됨, 1 row 만 남음) → generated=1 |
| 8 | `synced_to_render` reset 2,121 row + `sync_to_render.py` 실행 | inserted=1, updated=2,120, errors=0 |
| 9 | 사후 검증 | widget coverage **100%** (2,901/2,901), 전체 18.0% → 64.6% |

### 비용 (실측)

- 1회 backfill: ~$0.10 (실측, 시뮬 추정 $0.09 와 부합)
- 평균 입력 토큰: ~150/row (title+org), 출력 ~50/row
- 일일 신규 (5/18~): ~$0.003/일 (예상)

---

## 다음 사이클 (Phase 2.1 / Phase 3 / Phase 4)

### Phase 2.1 (작은 patch, 다음 사이클)

- `ai_summary_cache.py` UPDATE 에 `synced_to_render = 0` 추가 (수동 reset 불필요화)
- 같은 패턴: `ai_translate_cache.py` 도 확인 필요

### Phase 3 (별도 사이클, ~1~2일)

- `attachment_text` 컬럼 채우기 (PDF/HWP 텍스트 추출)
- `ai_summary` 입력 품질 향상 (현재 title+org 만 → 본문 기반)
- 비용: ~$10 + $18/년

### Phase 4 (별도 사이클, ~2~3일)

- `recommend_label` 활용 맞춤 추천
- 사용자별 가중치 정책 + UI
- 비용: ~$5 + $5/년

---

## 관련 문서

- 시뮬 entry: `docs/simulations/2026-05-17_phase2_ai_summary.md`
- 시뮬 INDEX: `docs/simulations/INDEX.md`
- release: `release/2026-05-17_b069_phase2_ai_summary/`
- daily: `docs/daily/2026-05-17.md`
- 선행 백로그: `docs/backlog/066_feature_impact_simulation_template.md`

---

## 변경 이력

| 일자 | 변경 | commit |
|---|---|---|
| 2026-05-17 EOD | 신설 — Phase 2 사후 문서 (backfill + sync 결과 명세) | TBD |
