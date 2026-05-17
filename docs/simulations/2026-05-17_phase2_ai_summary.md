# 2026-05-17 시뮬 — Phase 2 (AI 한줄요약 `ai_summary` 완비)

> **분류**: 영향 분석 (코드 변경 X, DB 변경 X)
> **대상**: `biz_projects.ai_summary` 컬럼 backfill + 일일 자동화 안정화
> **시점**: 5/17 EOD (b033 dedup 직후)
> **누적 entry**: 3 번째 (선행 b066 / b033)
> **결정 받기 전 진입 금지**

---

## 1. 작업 정의

### 1-A. 범위

- **PR1 backfill**: widget 노출 (`start_date >= 2026-01-01`) 대상 미생성 row 일괄 처리 (1회)
- **PR2 자동화**: `daily-crawl.yml` 의 `ai-summary` step 안정화 (이미 b069 로 도입 완료, 운영 검증만 남음)

### 1-B. Phase 분리 (사용자 비전)

| Phase | 목표 | 본 시뮬 |
|---|---|---|
| **Phase 2 (본 entry)** | `ai_summary` 완비 (widget 1,641 row + 일일 신규) | ✅ |
| Phase 3 | 첨부 분석 (`attachment_text` → 요약 입력 보강) | 별도 사이클 |
| Phase 4 | 맞춤 추천 (`recommend_label` 활용) | 별도 사이클 |

### 1-C. 의도된 결과

- 위젯 5/20 시연 시점에 `ai_summary` coverage 100% (widget 대상)
- 일일 신규 50건 자동 처리 (사용자 개입 0)
- 비용 한도: 첫 1회 ≤ $0.30, 월 ≤ $0.20

---

## 2. 현재 상태 정밀 분석 (실측, b033 직후)

### 2-A. 전체 분포

| source | total | `ai_summary` 보유 | % | 미생성 |
|---|---:|---:|---:|---:|
| bizinfo | 2,862 | 175 | 6.1% | **2,687** |
| kstartup | 537 | 410 | 76.4% | 127 |
| jbbi | 373 | 25 | 6.7% | 348 |
| kseafood | 244 | 1 | 0.4% | 243 |
| at_global | 206 | 5 | 2.4% | 201 |
| jbtp | 142 | 128 | 90.1% | 14 |
| jbtp_related | 74 | 2 | 2.7% | 72 |
| jbexport | 72 | 67 | 93.1% | 5 |
| **전체** | **4,510** | **813** | **18.0%** | **3,697** |

### 2-B. 처리 대상 세분화 (실제 backfill 대상)

| 정의 | 행수 |
|---|---:|
| 미생성 + `title` 보유 (생성 가능) | 3,387 |
| 미생성 + `attachment_text` 보유 (양질 입력) | **0** |
| 미생성 + 최근 30일 신규 | 2,029 |
| 미생성 + 진행중 (`end_date >= today`) | 72 |
| **미생성 + widget 대상 (`start_date >= 2026-01-01`)** | **1,641** ← Phase 2 핵심 |

### 2-C. 진행중 + 미생성 source 별 (가장 시급)

| source | 행수 |
|---|---:|
| kstartup | 52 |
| kseafood | 7 |
| at_global | 6 |
| jbbi | 5 |
| bizinfo | 2 |
| **합계** | **72** |

### 2-D. ai_summary 활동 이력

- 최초 생성: 2026-04-24 06:48 UTC
- 최근 생성: **2026-05-17 13:32 UTC (오늘, b069 step 작동 확인)**
- 24일 누적 813건 → 평균 ~34건/일 (현행 trickle 속도)

---

## 3. 모듈 / 인프라 정밀 분석

### 3-A. `pipeline/ai_summary.py` (이미 존재)

- **모델**: `gpt-4o-mini`
- **prompt**: "정부 지원사업 공고를 한 줄로 요약. 핵심 지원 내용과 대상 50자 이내."
- **max_tokens=100, temperature=0.3**
- **graceful skip**: `OPENAI_API_KEY` 부재 → 빈 문자열 반환 (파이프라인 중단 X)

### 3-B. `pipeline/ai_summary_cache.py` (이미 존재)

- **입력 우선순위** (`_source_text_for_item`):
  1. `attachment_text` (현재 0건)
  2. `description` (현재 1건만 length>50)
  3. `title + organization` (fallback — **현실은 거의 100% 이 경로**)
- **모드 3 종**:
  - 기본: mail 후보 (신규 7d + ending_soon URGENT)
  - `--source/--status/--end-date-from`: 필터 backfill
  - `--widget-targets`: `start_date >= 2026-01-01` 위젯 노출 대상 (b069 신설)
- **batch 패턴**: `BATCH_SIZE=10`, `COMMIT_INTERVAL=50` (b066 cycle2 학습 반영)
- **멱등**: `WHERE ai_summary IS NULL` (overwrite 옵션 별도)

### 3-C. `daily-crawl.yml` (b069 step 이미 추가됨)

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

- summary step 의 outcome 검사 대상 (`O_AISUMMARY`) — 단 critical 분류 X (warn only)
- timeout 10분, `continue-on-error: true` (sync step 진행 보장)

### 3-D. `run_all.py:392` (legacy hook)

- `python -m pipeline.ai_summary_cache` (flag 없음 → mail mode)
- non-fatal 처리 (`# [run_all] non-fatal: ai_summary_cache exit ...`)
- **중복 처리 위험**: Actions 의 widget step 과 동시에 작동하면 같은 row 두 번 호출 가능
- 단 `WHERE ai_summary IS NULL` 멱등 → 한쪽이 먼저 채우면 다른쪽 skip → 비용 낭비 X

---

## 4. 자동화 작동 여부 (5/17 진단)

| 환경 | hook | mode | 작동 |
|---|---|---|---|
| v1 PC `run_all.py` | `--mode all` | mail 후보 만 | ✅ |
| v1 Actions `daily-crawl.yml` | b069 step | widget 200/일 | ✅ (오늘 13:32 작동 확인) |
| Render | 미적용 | — | N/A (정적 데이터는 sync 로 받음) |
| v2 dev | 미적용 | — | 별도 사이클 |

### 4-A. 5/17 진단 결론

- 자동화 hook 은 정상. trickle 속도 200/일 → widget 1,641 클리어에 **약 9일** (5/26 EOD 예상)
- 5/20 시연 시점 도달 가능 row: 1,641 - (3일 × 200) = 1,041 = **여전히 63% 미생성**
- → **수동 backfill 필요** (5/18 새벽 1회 일괄)

---

## 5. 비용 시뮬

### 5-A. 1회 backfill (widget 1,641 row)

| 항목 | 추정 |
|---|---|
| input 토큰 / row | ~150 (title+org 만, 본문 부재) |
| output 토큰 / row | ~50 (50자 요약) |
| 단가 (gpt-4o-mini) | $0.150/M input, $0.600/M output |
| 1회 input 총 | 1,641 × 150 = 246K → $0.037 |
| 1회 output 총 | 1,641 × 50 = 82K → $0.049 |
| **1회 backfill 총** | **~$0.09** (사용자 가정 $0.18~0.30 의 1/3) |

### 5-B. 일일 신규 (5/18~)

- 평균 신규 ~50건/일 (실측)
- 비용 / 일: 50 × ($0.0000225 + $0.00003) = $0.00276
- 월: $0.083, 연: $1.00

### 5-C. 전체 처리 (3,697 row, widget 외 포함) — Phase 2.5

- backfill: ~$0.20
- 단 widget 외 row 는 사용자 노출 거의 없음 → ROI 낮음
- **권장: 보류** (Phase 3 첨부 분석 후 재검토)

---

## 6. 잠재 사고 시나리오

### 6-A. 5/17 b066 패턴 재발 (시간 추정 실패)

- 5/17 b066 cycle1: batch 미적용 → 4~5h 예상 → 실제 5h (정확도 85%)
- 본 사이클: batch_size=10 이미 적용 → 1,641 / 10 = 164 batch → ~30분 (실측 ai_translate 와 동급)
- **위험 낮음** (검증된 패턴 재사용)

### 6-B. title+org 만으로 hallucination

- description / attachment_text 가 0건 → GPT 는 title+org 만 보고 추측
- 예: title "2026 청년 창업 지원사업" + org "전북테크노파크" → GPT 가 지원금액 / 대상 임의 추정 위험
- **완화**: prompt "핵심 지원 내용과 대상 포함" → 본문 부재 시 일반 표현으로 수렴 (예: "전북지역 청년 창업 지원")
- **검증 필요**: 생성 후 sampling 10건 사용자 review

### 6-C. 기존 ai_summary 덮어쓰기

- 코드 `WHERE ai_summary IS NULL` + `--overwrite` 미사용 → 안전 ✅

### 6-D. Actions step 부재 (b067 ai_translate 와 동일 우려)

- daily-crawl.yml 검사 완료 → b069 step 이미 추가됨 ✅
- 단 commit log 에 b069 단독 commit 부재 → b067 와 함께 9521634 에 squash 가능성
- **확인 필요**: `git show 9521634 -- .github/workflows/daily-crawl.yml`

### 6-E. b033 직후 schema 정합성

- `_ensure_schema.py` 의 36 컬럼 통합에 `ai_summary` / `ai_summary_at` 포함 (5/14 b065 phase 2-pre 에서 정합)
- v1 PC + Actions runner + Render 모두 정합 ✅

### 6-F. 운영 sync 영향

- backfill 후 `synced_to_render = 0` 으로 reset 되어야 함 (현재 코드 확인 필요)
- 미reset 시 운영 DB 는 옛 값 유지 → 위젯 효과 X
- **확인**: `update_db.py` / `sync_to_render.py` 의 `ai_summary` 변경 감지 로직

### 6-G. Render `/api/sync` whitelist

- 25 컬럼 whitelist (`/api/sync` payload) 에 `ai_summary` 포함되어야 함
- 미포함 시 backfill 결과가 운영에 미반영
- **확인 필요**: `appy.py` 의 sync endpoint payload 정의

---

## 7. 의존성

### 7-A. 사전 작업 (없으면 진행 불가)

- `.env` 의 `OPENAI_API_KEY` (PC backfill 용) — 이미 b066 에서 설정됨 ✅
- GitHub Secret `OPENAI_API_KEY` (Actions 용) — 이미 b067 에서 추가됨 ✅
- `_ensure_schema.py` 의 ai_summary 컬럼 — 이미 정합 ✅

### 7-B. 사후 작업 (이번 작업 후 발생)

- 위젯 SQL 의 `ai_summary` SELECT 확인 (b066 ai_friendly 처럼 누락 없는지)
- 시연 후 사용자 sampling 10건 review → prompt 개선 백로그 (Phase 2.1)
- Phase 3 첨부 분석 진입 시 `_source_text_for_item` 의 attachment_text 경로 재활성화

### 7-C. 정합 (병렬 진행 시)

- ai_friendly_summary (b066) 와 별도 컬럼 → 충돌 X
- 단 UI 표시 정책 확인: `ai_friendly_summary` vs `ai_summary` 표시 우선순위

---

## 8. 4 환경 영향

| 환경 | 영향 | 작업 |
|---|---|---|
| **v1 PC** | backfill 1,641 row 실행 | `py -m pipeline.ai_summary_cache --widget-targets --limit 2000` |
| **v1 Render** | sync 시점에 자동 반영 | `synced_to_render=0` reset 정책 확인 |
| **GitHub Actions** | 일일 200/일 trickle 유지 | 변경 X (이미 작동) |
| **v2 dev** | 영향 X | 별도 사이클 |

---

## 9. b033 dedup 와의 시너지

- b033 후 bizinfo: 15,625 → 2,862 (5.5배 감소)
- ai_summary forward_merge 2,861 보존 (b033 cycle 에서 명시)
- → **Phase 2 비용 5배 절감** (중복 처리 0)
- → 본 시뮬의 1회 backfill 비용 $0.09 = b033 의 직접 가치

---

## 10. 보완 1 — 5/17 b066 + b033 패턴 재사용

| 패턴 | 출처 | 본 사이클 적용 |
|---|---|---|
| `BATCH_SIZE=10, COMMIT_INTERVAL=50` | b066 cycle2 | ✅ 이미 코드 반영 |
| `WHERE ai_summary IS NULL` 멱등 | b066, b033 | ✅ 이미 코드 반영 |
| `timeout: 10분` Actions step | b067 | ✅ 이미 yaml 반영 |
| `continue-on-error: true` | b067 | ✅ 이미 yaml 반영 |
| `.env` + Secret 사용자 사전 작업 | b066, b067 | ✅ 사전 완료 |

→ **신규 인프라 0%**, 패턴 재사용 100%

---

## 11. 보완 2 — Phase 단계화 시간/비용

| Phase | 시간 | 비용 (1회 + 연간) | 위험 |
|---|---|---|---|
| **Phase 2 (본)** | 1~2h (검증 포함) | $0.09 + $1.00/년 | 낮음 |
| Phase 3 (첨부) | 1~2일 | ~$10 + $18/년 | 중간 |
| Phase 4 (추천) | 2~3일 | ~$5 + $5/년 | 중간 |

---

## 12. 보완 3 — 5/20 시연 영향

| 진행 시점 | 시연 효과 | 사용자 부담 |
|---|---|---|
| **5/18 새벽 (응모서 모드 전)** ✅ 권장 | widget coverage 100% | 낮음 (수면 후) |
| 5/17 EOD (오늘) | 동일 | 높음 (피로 누적) |
| 5/19 EOD | trickle 으로 ~85% 도달 | 낮음 (검증 시간 부족) |
| W21 (시연 후) | 시연 효과 X | 안정 우선 |

→ **5/18 새벽 권장**

---

## 13. 보완 4 — ROLLBACK plan

- DB 변경: UPDATE 만 (ALTER 0) → 롤백 단순
- 잘못된 ai_summary 발견 시:
  ```sql
  UPDATE biz_projects SET ai_summary=NULL, ai_summary_at=NULL
  WHERE ai_summary_at >= '2026-05-18T00:00:00Z'
  ```
- backup 권장: b033 직후 시점 (`db/biz.backup.2026-05-17_b033.db`) — 이미 존재하면 재사용
- Render sync 영향 시: `synced_to_render=0` reset 후 재sync

---

## 14. 보완 5 — 시뮬 정확도 학습 (선행 entry vs 실제)

### 14-A. b066 시뮬 vs 실제 (사용자 메모 기반)

| 항목 | 시뮬 | 실제 | 정확도 |
|---|---|---|---|
| 시간 | 4~5h | 5h | 85% |
| 사고 | 0건 | 2건 | 70% |
| 비용 | $2.85 | $2.50 | 95% |

### 14-B. b033 시뮬 vs 실제 (사용자 메모 기반)

| 항목 | 시뮬 | 실제 | 정확도 |
|---|---|---|---|
| 영향 row | 8,000+ | 12,884 | 60% |
| release package 존재 | 가정 | 부재 | 0% |

### 14-C. 본 사이클 (Phase 2) 개선점

- **실측 우선**: DB COUNT (1,641) 로 가정 (1k~1.5k) 검증 → 부합 ✅
- **인프라 사전 확인**: ai_summary.py / yaml step 존재 → 신규 작업 0
- **사용자 가정 비용 ($0.18~0.30) vs 실측 추정 ($0.09)**: 사용자 보수 추정의 1/3 — title+org 만으로 토큰 적음 반영
- **trickle 속도 진단 추가**: 200/일 → 9일 → 5/20 시연 시 63% 미생성 → backfill 결정 근거

---

## 15. 종합 추천

### 15-A. 진행 옵션

| 옵션 | 내용 | 적합 시점 |
|---|---|---|
| **A. 5/18 새벽 backfill** ✅ 권장 | 30분, 1,641 row, $0.09 | 응모서 모드 진입 전, 시연 사전 |
| B. trickle 만 유지 | 작업 0, 5/26 자동 완비 | 시연 영향 무시 가능 시 |
| C. 5/17 EOD 즉시 backfill | 30분, 즉시 | 컨디션 + 백업 준비 시 (사용자 피로 위험) |
| D. Phase 2.5 (전체 3,697) | 1h, $0.20 | widget 외 보강 필요 시 (ROI 낮음) |

### 15-B. 진행 시 작업 단위

| # | 작업 | 시간 | 위험 |
|---|---|---|---|
| 1 | b033 후 백업 확인 / 신규 백업 | 5분 | 낮음 |
| 2 | sampling 10건 dry-run 검증 (`--dry-run --limit 10`) | 5분 | 낮음 |
| 3 | widget backfill (`--widget-targets --limit 2000`) | 30분 | 중 (API 호출 양) |
| 4 | sync 영향 확인 (`synced_to_render` reset 검증) | 10분 | 중 |
| 5 | 위젯 표시 확인 (브라우저 sample 5 페이지) | 10분 | 낮음 |
| 6 | b069 백로그 문서 작성 + INDEX 갱신 | 10분 | 낮음 |

### 15-C. 사용자 결정 사항 (코드 진입 전)

1. **진행 시점**: A (5/18 새벽) / B (trickle 유지) / C (5/17 EOD)
2. **범위**: widget 만 (1,641) / 전체 (3,697)
3. **검증 강도**: dry-run 10건 / 50건 / skip
4. **운영 반영**: sync 즉시 / 다음 daily-crawl 대기
5. **시연 sampling review**: 5/19 EOD 10건 / skip
6. **b069 백로그 문서**: 신규 작성 / b067 entry 에 통합 / skip

---

## 16. 회고 (실제 진행 후 작성)

> 본 섹션은 진행 후 채움. 시뮬 정확도 측정용.

- 실제 처리 row: ___
- 실제 시간: ___
- 실제 비용: ___
- 발생 사고: ___
- 시뮬 미발견 항목: ___
- 본 템플릿 개선 제안: ___

---

## 변경 이력

| 일자 | 변경 | 작성 |
|---|---|---|
| 2026-05-17 | 신설 — 5/17 누적 시스템 3번째 entry, b069 사후 분석 + 5/18 backfill 결정 받기 | CC |
