# 2026-05-19 시뮬 — Phase 3.0 PoC 사전 정밀 시뮬 (11번째 가설 정정 발견)

> **분류**: 영향 분석 (코드 변경 X, DB 변경 X) — Phase 3.0 PoC 진입 직전
> **선행 entry**: [2026-05-17_phase3_attachment.md](2026-05-17_phase3_attachment.md), [2026-05-17_phase3_ai_integration.md](2026-05-17_phase3_ai_integration.md)
> **시점**: 5/19 D-1 (5/20 시연 직전)
> **누적 entry**: 7번째 (b066 / b033 / Phase 2 / Phase 3 1차 / Phase 3 통합 / 본 PoC 사전)
> **사용자 목적**: 정규식 4종 실측 검증 → PoC 정확도 사전 예측 + 위험 사전 차단

---

## 🚨 11번째 가설 정정 (PoC 시뮬에서 발견, 사용자 9/10 가설 부분 정정)

| 가설 (9/10번째 통합) | 실측 (5/19 PoC sim) | 정정 |
|---|---|---|
| bizinfo "본문" 에 "신청기간" 명시 → description 컬럼 활용 가능 | **bizinfo `description` 컬럼 = 날짜 문자열 '2026-04-03' (avg 8자, max 10자)** — 본문 X | description 은 misnamed (실제로 등록일자) / 본문 자체가 DB 부재 |
| 정규식 4종 적용 1~2h | **본문이 DB 에 없어 정규식 적용 대상 자체가 없음** | Phase 3.0 본질 = "본문 fetch" 로 회귀 |
| 단순 라벨 파싱 | **`fetch_detail()` + `--enrich-detail` 플래그 + `_parse_detail_soup()` + `_extract_period_status_from_detail_table()` 이미 존재** (`connector_bizinfo.py`) | Phase 3.0 코드 변경 0, **기존 스크립트 실행만 필요** |

→ **Phase 3.0 = `py connectors/connector_bizinfo.py --enrich-detail` 실행** (2,125 row HTTP fetch, wall clock 35~70분)
→ 코드 변경 0, 시간 1~2h (테스트 + DRY-RUN 포함, 기존 추정 유지)
→ 사용자 가설 정정 누계: **11건**

---

## 1. PoC 사전 정밀 조사 결과

### 1-A. bizinfo 확인 필요 (2,242건) 컬럼 충전율

| 컬럼 | 채워짐 | % | 비고 |
|---|---|---|---|
| `title` | 2,242 | 100.0% | ✓ |
| `organization` | 2,242 | 100.0% | ✓ |
| `url` | 2,241 | 100.0% | ✓ (1건만 NULL) |
| `description` | 2,165 | 96.6% | ⚠️ **날짜 문자열 (본문 X, 평균 8자)** |
| `ai_summary` | 2,126 | 94.8% | ✓ (Phase 2 결과, 본문은 crawl 시점에만 일시 존재한 듯) |
| `start_date` | 2,165 | 96.6% | ✓ |
| `receipt_end` | 92 | 4.1% | (구조화 마감일 — 추출 대상) |
| `end_date` | 0 | 0.0% | ❌ **status='확인 필요' 원인** |
| `period_text` | 0 | 0.0% | ❌ 파이프라인 미실행 |
| `attachments_json` | 0 | 0.0% | ❌ (5/17 통합 시뮬에서 발견) |
| `attachment_text` | 0 | 0.0% | ❌ |
| `biz_end` / `ministry` / `raw_status` / `apply_url` | 0 | 0.0% | ❌ |

### 1-B. source 별 description 평균 길이

| source | total | avg | max | 본문 여부 |
|---|---|---|---|---|
| bizinfo | 2,980 | **8** | 10 | ❌ 날짜 문자열 |
| kstartup | 592 | 3 | **2,000** | △ 일부 본문 / 평균 매우 짧음 |
| 6 others (kseafood, jbtp_related, jbtp, jbexport, jbbi, at_global) | — | **0** | 0 | ❌ 빈 문자열 |

→ **본문은 어느 source 도 DB 에 안정적으로 저장 안 됨**.

### 1-C. 정규식 4종 매칭 시도 결과

- 대상: bizinfo 확인 필요 + `length(description) > 50` 샘플 200건
- 결과: **0 row 매칭 가능** (description 이 본문이 아닌 날짜 문자열이라 정규식 적용 대상 부재)
- → 정규식 4종 적용 의미 X 까지는 아님: **`fetch_detail()` 실행 후 새로 받은 본문**에 적용 가능

### 1-D. 기존 인프라 발견 (가장 큰 가치)

`connectors/connector_bizinfo.py` 내 이미 존재:

| 함수 | 역할 |
|---|---|
| `fetch_detail(url, session)` | 단일 URL HTTP fetch + `_parse_detail_soup()` 호출 |
| `_parse_detail_soup(soup, url, html)` | 메타 추출 (title, organization, ministry, period, status, attachments_json) |
| `_extract_period_status_from_detail_table(soup)` | **테이블 구조 기반 신청기간/상태 추출** (5/19 10번째 가설의 정규식 4종을 대체) |
| `--enrich-detail` 플래그 | CLI 진입점 |

→ 사용자 가설 (정규식 4종 신규 작성) 대신 **기존 함수 호출만으로 충분**.
→ 단, `_extract_period_status_from_detail_table()` 의 매칭 정확도는 PoC 직접 측정 필요.

---

## 2. Phase 3.0 재정의 (5/19 11번째 정정)

### 2-A. 본 작업

```bash
# DRY-RUN — 10건 샘플 (`--limit 10` 권장)
py connectors/connector_bizinfo.py --enrich-detail --limit 10

# 본 실행 — 2,125 확인 필요 + url 보유 row
py connectors/connector_bizinfo.py --enrich-detail
```

### 2-B. 시간 추정

| 단계 | 작업 | 시간 |
|---|---|---|
| 1 | `--enrich-detail` 플래그 의미 확인 (코드 read) | 10분 |
| 2 | DRY-RUN 10건 (HTTP 요청 1-2s × 10 = ~20s, 매칭률 확인) | 20분 |
| 3 | 매칭률 ≥80% 시 본 실행 (2,125 row × 1.5s = ~50분) | 50~70분 |
| 4 | 매칭률 <80% 시: AI fallback 정책 + 신규 정규식 추가 | +1~2h |
| 5 | `infer_status` 재실행 + DB UPDATE 검증 | 10분 |
| **합계** | | **1.5~3h** (이전 1~2h 추정 유지) |

### 2-C. 예상 성과 (PoC 직후 측정)

- 확인 필요 2,125 → **300~600 감소 추정** (10번째 정정 사례 KIAT/KICET 처럼 신청기간 명시 보편적이라 가정)
- 단, `_extract_period_status_from_detail_table()` 매칭 실패 row 는 별도 정규식 + AI fallback

### 2-D. AI fallback 비용 추정

가정: 정규식 + table 추출 합산 커버율 80%

- AI fallback 대상: 2,125 × 20% = 425 row
- GPT-4o-mini 본문 1~2K token × 425 = ~$1.7 (1회성 backfill)
- 일일 신규 ~30 × 20% = 6 row × $0.001 = $0.006/day → 연 ~$2.2
- **총 추가 비용: ~$4** (5/17 합계 $2.94 + 본 ~$4 = ~$7 누적)

---

## 3. 위험 + 대응 (PoC 직전 정밀화)

| # | 위험 | 확률 | 대응 |
|---|---|---|---|
| A | `_extract_period_status_from_detail_table()` 가 기관별 본문 구조 (10번째 정정) 못 잡음 | 중 | DRY-RUN 10건 매칭률 직접 측정 → ≥80% 통과 시 진행 / 미만 시 정규식 4종 추가 |
| B | bizinfo 사이트 access 차단 / rate limit | 낮음 | `time.sleep(1)` 또는 `requests.Session()` 재사용 (이미 코드에 적용된 듯) |
| C | HTTP 요청 50~70분 중 네트워크 끊김 | 중 | 멱등성 (WHERE end_date IS NULL 만 처리) 으로 재실행 안전 |
| D | URL NULL row 1건 + 빈 description 77건 처리 | 낮음 | `WHERE url IS NOT NULL AND url != ''` 필터 |
| E | `_parse_detail_soup()` 가 본문을 DB 에 어떻게 쓰는지 미확인 | 중 | 코드 read 10분 (`update_db.py` 또는 connector 내 UPDATE 로직 확인) |
| F | 운영 Render DB 와 sync 정책 | 중 | bizinfo enrich 결과는 v1 PC master / Render 는 메타만 sync (Phase 2.1 patch 와 통합) |

---

## 4. 사이클 1 차단 체크리스트 (5/17 학습)

| # | 항목 | 본 PoC |
|---|---|---|
| 1 | DB 실측 우선 | ✓ (description / period_text / end_date 충전율 측정) |
| 2 | 인프라 재사용 비율 측정 | ✓ **`fetch_detail()` + `--enrich-detail` 100% 재사용** |
| 3 | batch + chunked commit | ✓ (HTTP 요청 자체가 row-by-row, commit 은 _ensure 패턴) |
| 4 | DRY-RUN + --limit 10 | ✓ 명시 |
| 5 | 단계 분할 | △ Phase 3.0 만 1~2h 이라 분할 불필요 |
| 6 | 신규 backup | ✓ DRY-RUN 직전 |
| 7 | 운영 sync 정책 | ✓ 메타만 sync, 본문 PC only |
| 8 | 회고 entry backfill | ✓ PoC 후 즉시 회고 갱신 |

→ **8/8 통과** (5/17 패턴 적용).

---

## 5. 응모서 가치 (#2 누적 학습 강화)

> 5/17 ~ 5/19 시뮬 사이클 (3일):
>
> 사용자 가설 정정 **11건**.
>
> 본 PoC 사전 시뮬 (5/19) 사례:
> - 사용자 가설 (9, 10번째): "bizinfo 본문 파싱 1~2h"
> - PoC 사전 측정: description 컬럼이 본문 X (날짜 문자열), 본문은 DB 부재
> - 진짜 발견: **기존 `--enrich-detail` 스크립트만 실행하면 됨** (코드 변경 0)
>
> → **"선 분석, 후 진행" 본능의 진짜 작동.**
> → 잘못된 가설로 코드 작성 직진 시 사고 위험 (정규식 4종 신규 작성 후 매칭 0% 발견 등).
> → 본 시뮬 30분 = 사고 1~2일 사전 차단.

---

## 6. 다음 진입 조건

- [x] DB 실측 본 entry 완료
- [x] `connector_bizinfo.py` `fetch_detail` 코드 read (5/20 Step 1 완료)
- [x] DRY-RUN 10건 매칭률 측정 (5/20 Step 2 — **90% ≥ 80% 통과**)
- [ ] **5/20 시연 종료 + 회복**
- [ ] Phase 3.0 PoC 본 실행 (5/22 권장)

---

## 7. 🟢 5/20 PoC Step 1+2 실측 검증 (12번째 가설 정정)

코드 read + DRY-RUN 10건으로 본 시뮬(11번째 정정)의 PoC 명세를 추가 검증한 결과,
**11번째 정정도 부분적으로 틀림** — 4건 추가 정정.

| 11번째 정정 가설 | 5/20 코드 실측 | 정정 |
|---|---|---|
| `--enrich-detail` = 2,125 row HTTP fetch → DB 반영 | `db/biz.db` 미접근. `bizinfo_all.json` JSON-only read/write | 위험 E 정정: connector 에 DB UPDATE 없음. merge 파이프라인 별도 |
| DRY-RUN = `--enrich-detail --limit 10` | `--dry-run` / `--limit` 플래그 부재 (argparse 오류) | 실제 = `--enrich-max` + `--out`, 또는 함수 import 스크립트 |
| 대상 2,125 row | `bizinfo_all.json` 1,433 row (end_date 없음) | DB 2,242 는 누적, JSON 은 단일 크롤 스냅샷 |
| `_extract_period_status_from_detail_table()` = 매칭 핵심 | DRY-RUN 10건 전부 `period_th` 빈 값. 실제 매칭 = `_extract_period_from_s_title_list()` | th/td 테이블 X → s_title 리스트 레이아웃 |

### DRY-RUN 10건 매칭률

- fetch 10/10 성공 (네트워크 실패 0)
- end_date 추출 **9/10 = 매칭률 90%**
- 1건 실패 = "예산 소진시까지" (공고 자체 마감일 부재, 파싱 버그 X)
- 표본 편향: 선두 10건 = 최근 지자체 공고 위주, KIAT/KICET 국가기관 미포함 → 본 실행 시 전체 재측정 필요

→ 1번째 시뮬이 "코드 변경 0" 발견, 2번째 검증(코드 read)이 "실행 명세 자체가 틀림" 발견.
→ 상세: `docs/daily/2026-05-20_phase3_poc_step1_2.md`

---

## 관련 파일

- 1차 sim: `docs/simulations/2026-05-17_phase3_attachment.md`
- 통합 sim: `docs/simulations/2026-05-17_phase3_ai_integration.md`
- 응모서 카피: `docs/proposal/2026-07-03_jbtp_intro_copy.md`
- 핵심 코드: `connectors/connector_bizinfo.py` (28KB)
- 핵심 함수: `fetch_detail`, `_parse_detail_soup`, `_extract_period_status_from_detail_table`
- CLI flag: `--enrich-detail` (line 8, 10)
