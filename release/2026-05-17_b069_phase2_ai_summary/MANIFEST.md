# b069 Phase 2 AI 한줄요약 완비 — 2026-05-17 EOD

## 배경

- Phase 2 = `ai_summary` 컬럼 완비 (위젯 노출 대상 100%)
- 선행 b033 (bizinfo dedup) 직후 — 중복 정리로 처리 대상 5배 감소
- 선행 b066/b067 의 batch + Actions step 패턴 재사용 (신규 인프라 0%)

## 실측 결과

| 항목 | 사전 | 사후 | 증감 |
|---|---:|---:|---:|
| 전체 `ai_summary` 보유 | 813 / 4,510 (18.0%) | 2,914 / 4,510 (64.6%) | +2,101 (+46.6%p) |
| **widget 대상 (`start_date >= 2026-01-01`)** | — | **2,901 / 2,901 (100%)** | — |
| sync pending | 0 | 0 (전체 push 완료) | — |

## 실행 흐름 (Step 7~9)

### Step 7: backfill (`pipeline.ai_summary_cache --widget-targets --limit 2000`)

- 사전 백업: `db/biz.backup.20260517_224529_pre_phase2.db` (SHA256 매칭 PASS)
- dry-run 10 검증 PASS
- 실행: `pending=1` (선행 cron 이 13:26~13:45 사이 1,640 처리됨), generated=1, failed=0

### Step 8: v1 → 운영 sync

- `synced_to_render = 0` reset (오늘 `ai_summary_at >= 2026-05-17` 인 2,121 row)
- `pipeline/sync_to_render.py` 실행 → POST `/api/sync`
- 결과: **inserted=1, updated=2,120, errors=0, batches_fail=0**
- 7 source 모두 OK (at_global 75, bizinfo 1,852, jbbi 9, jbexport 5, jbtp 15, kseafood 28, kstartup 137)

### Step 9: 사후 검증

- DB 분포 재확인 (위 표)
- Render endpoint GET / 200 OK, HTML 에 `ai_summary` 노출 확인
- sync pending after run = 0

## 비용 (실측)

- 1회 backfill (2,121 row): ~$0.10 (시뮬 추정 $0.09 와 부합)
- 일일 신규 (5/18~): ~$0.003/일, 월 ~$0.09, 연 ~$1.10

## ⚠️ 사후 발견 (다음 사이클 fix)

### `ai_summary_cache.py` 의 UPDATE 가 `synced_to_render` reset 안 함

- backfill 후 sync 가 push 할 row 0 → 운영 미반영 위험
- 본 사이클은 수동 SQL reset 으로 우회
- **Phase 2.1 patch**: `ai_summary_cache.py` UPDATE 에 `synced_to_render = 0` 추가
- 같은 패턴: `ai_translate_cache.py` (b066) 도 확인 필요

## ROLLBACK

```powershell
cp db/biz.backup.20260517_224529_pre_phase2.db db/biz.db
py pipeline/sync_to_render.py  # 운영 재sync (백업 시점 상태로)
```

복구 시간: < 5분 (단 backup 시점 = backfill 직전 = 813 ai_summary 상태로 회귀)

## 의존성

- b033 (bizinfo dedup) → 처리 대상 5배 감소 (시너지)
- b066 (batch 패턴) → BATCH_SIZE=10, COMMIT_INTERVAL=50 재사용
- b067 (Actions step 패턴) → daily-crawl.yml 의 ai-summary step 패턴 재사용

## 사이클 분리

- **본 사이클**: Phase 2 = `ai_summary` 완비
- **Phase 2.1** (다음 사이클): sync flag reset patch
- **Phase 3** (별도): 첨부 분석 (`attachment_text`)
- **Phase 4** (별도): 맞춤 추천 (`recommend_label`)

## 시뮬 정확도 (사전 vs 사후)

| 항목 | 시뮬 추정 | 실측 | 정확도 |
|---|---|---|---|
| widget 처리 대상 | 1,641 | 2,121 (오늘 누적) / pending 시점 1 | 부분 (선행 cron 동시 작동 미예측) |
| 비용 | $0.09 | ~$0.10 | 90% |
| 시간 | 30분 | 1분 (pending=1 만 남음) | — |
| 사고 | 0건 (사전 검증 풍부) | 1건 발견 (synced_to_render reset 누락) | 70% |

→ 시뮬에서 미발견 한 sync flag reset 누락이 사후 학습 항목. 다음 시뮬 entry 에 반영.

## 관련 문서

- 시뮬: `docs/simulations/2026-05-17_phase2_ai_summary.md`
- 백로그: `docs/backlog/069_phase2_ai_summary.md`
- daily: `docs/daily/2026-05-17.md`
