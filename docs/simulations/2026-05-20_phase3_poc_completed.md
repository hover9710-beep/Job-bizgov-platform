# 2026-05-20 시뮬/회고 — Phase 3.0 PoC 완료 (13번째 가설 정정)

> **분류**: PoC 실행 회고 (코드 변경 X — read + execute + docs)
> **선행 entry**: `2026-05-19_phase3_poc_pre_simulation.md` (11·12번째 정정)
> **시점**: 5/20 (박람회 마지막 날 + 시연 + 집 작업)
> **결과**: PoC end-to-end 검증 성공 + **13번째 가설 정정** (enrich 비영구성)

---

## 🚨 13번째 가설 정정 — "PoC 실행 ≠ Phase 3 본 구현"

| 가설 (5/20 오전) | 실측 (5/20 밤) | 정정 |
|---|---|---|
| "`--enrich-detail` 실행만 = Phase 3.0 완성" | enrich 결과는 **비영구** — 야간 크롤(20:37)이 `bizinfo_all.json`을 덮어쓰고, `update_db` UPDATE가 보존 가드 없이 DB `end_date`를 빈값으로 덮어씀 | Phase 3 본 구현의 핵심 = enrich 실행이 아니라 **"영구화"** |
| Step 3(enrich) → Step 4(merge) 2일 간격 OK | 그 사이 야간 크롤이 매일 결과를 wipe → **5/20 오전 enrich 513건 소멸** (DB 0건 반영) | enrich+merge는 야간 크롤 주기(<1일) 내 원자적 수행 필요 |

→ 누적 가설 정정 **13건** (5/17~5/20)
→ **"30분 검증 = Phase 3 본 구현 명세 명확화"**

---

## 1. 발견 경로

1. 5/20 오전: `--enrich-detail` 본 실행 → 박람회장 네트워크로 823건 실패, 513건만 성공 (부분)
2. 5/20 밤 재실행 직전 사전 점검: `bizinfo_all.json` end_date **517 → 4** 발견
3. 원인 추적: 파일 mtime 20:40:50 = 야간 크롤이 같은 파일을 덮어씀
4. `update_db.py` 코드 read: UPDATE 문에 `end_date` 보존 가드 부재 → DB 반영해도 다음 야간 wipe
5. → enrich 비영구성 = **2중 구조 문제** 확정

## 2. PoC 정량 결과 (검증된 실측)

| 항목 | 값 |
|---|---|
| 재실행 fetch | 1,474 / 1,474 (네트워크 실패 **0건**) |
| `bizinfo_all.json` end_date | 4 → **767** (51.9%) |
| **파싱 정확성** | **100%** — fetch 1,474건 전수 period 필드 정상 추출 |
| 무마감 공고 | 711건 (48.1%) — "예산소진/선착순/상시/세부사업별 상이", **정당한 추출** (마감일 부재) |
| DB bizinfo end_date | 738 → **1,500** (+762) |
| **DB bizinfo 확인 필요** | 2,302 → **1,446** (−856, **−37%**) |

5/20 오전 매칭률 84.1%는 네트워크 점진 악화로 리스트 앞부분(마감일 명확 공고)만 성공한 **편향 표본**. 전수 측정 51.9%가 진짜 비율.

## 3. 2중 wipe 메커니즘

```
① JSON: connector_bizinfo.py 기본 run() = 야간 20:37 크롤 → bizinfo_all.json 덮어씀
② DB  : update_db.py UPDATE 문에 end_date 보존 가드 없음
         (attachments_json·organization 등엔 5/12 사고 대응 가드 있으나 end_date엔 없음)
         → 야간 merge가 빈 end_date로 DB 덮어씀
```

→ Step 4로 DB에 넣어도 **다음 야간 파이프라인이 wipe**. 영구화 없이는 매일 원위치.

## 4. Phase 3 본 구현 = 영구화

PoC가 명확히 한 것: Phase 3 본 구현 = enrich 실행이 아니라 **영구화 + status 재분류**.

- 백로그 ① `enrich_persistence.md` — 영구화 (야간 파이프라인 통합 / update_db 가드), 2~4h, 우선순위 높음
- 백로그 ② `no_deadline_classification.md` — 무마감 ~700건 status 재분류, 30분~1h, 우선순위 중

## 🚨 14번째 가설 정정 (5/21 검증 중 발견)

| 가설 | 실측 | 정정 |
|---|---|---|
| `run_pipeline.py` = 야간 파이프라인 | 야간 스케줄러(`auto_run.bat`)·GitHub Actions(`daily-crawl.yml`)는 **`run_all.py`** 사용. `run_pipeline.py`는 수동 웹 버튼(`appy.py` `POST /run`) 전용 | Phase 3 본 구현 ①A(enrich 자동화)를 `run_pipeline.py`에 넣어 **야간 경로 미반영** |

- ②·①B는 `update_db.py` 경유라 운영 반영됨 (`run_all.py`가 `update_db.py` 호출)
- ①A만 오배치 — `run_pipeline.py`가 운영 경로라는 가정(5/20 Step 1+2 데일리에서 시작)을 검증 없이 승계
- 발견 경로: "운영 sync 명확화" 작업 중 `run_all.py`·`daily-crawl.yml` 정독 → 오배치 포착 (출시 전)
- **교훈**: 파이프라인 작업은 스크립트 이름("통합 파이프라인")이 아니라 **운영 진입점(스케줄러 task / CI yml)부터 역추적**
- **해소 (5/21)**: enrich 단계를 `run_all.py` `run_bizinfo()`에 통합 — `docs/backlog/enrich_in_run_all.md` (commit `db5f6bb`, `run_all.py --mode bizinfo` 검증 통과)

→ 누적 가설 정정 **14건**. '선 분석 → 구현 → **검증**'의 검증 단계가 오류를 잡고 같은 날 해소한 사례.

---

## 관련 파일

- 선행 시뮬: `docs/simulations/2026-05-19_phase3_poc_pre_simulation.md`
- PoC 데일리: `docs/daily/2026-05-22_phase3_poc_completed.md`
- 백로그: `docs/backlog/enrich_persistence.md`, `docs/backlog/no_deadline_classification.md`
- DB 롤백 지점: `db/biz.backup.20260520_234520_pre_step4_merge.db`
