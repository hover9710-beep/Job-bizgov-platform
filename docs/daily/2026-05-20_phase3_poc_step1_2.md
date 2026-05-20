# 2026-05-20 — Phase 3.0 PoC Step 1 + Step 2 (코드 read + DRY-RUN 10건)

> **시점**: 5/20 시연 D-day 오전 (박람회 일정 전)
> **범위**: Step 1 (코드 read) + Step 2 (DRY-RUN 10건). DB 변경 X / JSON 변경 X.
> **결과**: 매칭률 **90%** (9/10) + **12번째 가설 정정** (위험 E 모델 오류 등 4건)
> **본 실행 (Step 3)**: 미진입 — 5/22 권장 (사유 하단)

---

## 🚨 12번째 가설 정정 — 코드 read 가 LATEST.md PoC 명세 4건 정정

| # | LATEST.md / 11번째 sim 가설 | Step 1 코드 실측 | 정정 |
|---|---|---|---|
| 1 | `--enrich-detail` = **DB 2,125 row UPDATE**, 멱등성 `WHERE end_date IS NULL` | `--enrich-detail` 는 **`db/biz.db` 를 일절 건드리지 않음**. `data/bizinfo/json/bizinfo_all.json` (JSON 파일) 만 read/write | 위험 E 정정: connector 에 DB UPDATE 로직 자체가 없음. DB 반영은 별도 merge 파이프라인 |
| 2 | DRY-RUN 명령 = `--enrich-detail --dry-run --limit 10` | `--dry-run` / `--limit` 플래그 **미존재** → argparse 오류로 즉시 실패 | 실제 대응 = `--enrich-max N` (테스트용) + `--out` (원본 JSON 보호) |
| 3 | enrich 대상 = **2,125 row** | `bizinfo_all.json` = 1,437 row 중 end_date 없음 **1,433 row** (전부 url 보유) | DB 2,242 "확인 필요" 는 누적, JSON 은 최신 단일 크롤 스냅샷 → "2,125" 는 과대 추정 |
| 4 | 매칭 핵심 = `_extract_period_status_from_detail_table()` (정규식 4종 대체) | DRY-RUN 10건 전부 `period_th` **빈 값**. 실제 매칭 = `_extract_period_from_s_title_list()` (s_title 리스트 레이아웃) | 현재 bizinfo 상세는 th/td 테이블 X → 10번째 정정의 "table 기반 추출" 도 레이아웃 오인 |

→ **사용자 가설 정정 누계: 12건** (5/17~5/20, 4일)
→ 30분 사전 작업 (코드 read 10 + DRY-RUN 15 + 분석 5) = 잘못된 멘탈모델 4건 직진 차단

---

## A. Step 1 — 코드 read 결과

대상: `connectors/connector_bizinfo.py` (842 line)

### 핵심 함수 (line + 로직 요약)

| 함수 | line | 로직 요약 |
|---|---|---|
| `fetch_detail(url, session)` | 168–205 | URL 에서 `pblancId` seq 추출 → `_detail_url_from_seq` 로 상세 URL 조립 → `session.get(timeout=max(TIMEOUT,25))` → `_parse_detail_soup`. **Session 은 호출자가 주입 (재사용 ✓)**. `fetch_detail` 자체에 sleep 없음 |
| `_parse_detail_soup(soup, url, html)` | 373–418 | title(4 selector)·body·ministry·organization·period·status 추출. 반환 dict 키: title/body/organization/ministry/executing_agency/**period**/period_th_table/period_label_map/period_html_grep/**status**/url. ⚠️ **attachments_json 생성 안 함** (시뮬 가정과 다름) |
| `_extract_period_status_from_detail_table` | 208–226 | th/td 테이블 스캔. `<th>` 라벨이 접수/신청/공고/모집/사업기간 → 다음 `<td>` = period. ⚠️ DRY-RUN 10건 전부 빈 값 |
| `_extract_period_from_s_title_list` | 229–244 | `ul>li>span.s_title + div.txt` 레이아웃 → 라벨→값 맵. ⭐ **실제 매칭 담당** |
| `_grep_application_period_from_html` | 256–294 | raw HTML/JSON 키 정규식 fallback |
| 우선순위 (line 402) | — | `period_from_labels or period_th or period_grep` — s_title 리스트 1순위 |

### CLI 플래그 (line 763–809)

| 플래그 | 의미 |
|---|---|
| `--enrich-detail` | `run_enrich_detail_from_file()` 진입 (line 811–821) |
| `--enrich-in PATH` | 입력 JSON (기본 `bizinfo_all.json`) |
| `--enrich-max N` | 최대 처리 건수 — **`--limit` 대응** |
| `--enrich-force-all` | end_date 있어도 재요청 |
| `--out PATH` | 출력 JSON 경로 (미지정 시 입력 파일 덮어씀) |
| ~~`--dry-run`~~ ~~`--limit`~~ | **존재하지 않음** |

### UPDATE 로직 — 위험 E 차단 결과

`run_enrich_detail_from_file()` (line 659–760):

- 입력: `bizinfo_all.json` **JSON 파일** (`db/biz.db` 아님)
- 멱등성: `skip_if_has_end and row['end_date']` (line 707) — **JSON row-level skip**, SQL `WHERE` 아님. `--enrich-force-all` 로 해제
- 갱신 필드 (JSON row): title/organization/description/period/raw_period/period_text/start_date/**end_date**/status (line 742–751)
- 저장: `out_path.write_text(...)` (line 755) — JSON 덮어쓰기
- ⚠️ `db/biz.db` 접근 코드 **0건** / `end_date_inferred` 필드 **없음** (실제 필드명 `end_date`)

### JSON → DB 경로 (위험 E 후속)

```
connector_bizinfo.py --enrich-detail   →  bizinfo_all.json 갱신
pipeline/merge_sources.py (find_bizinfo_file_legacy)  →  병합
pipeline/run_pipeline.py  →  db/biz.db 반영
```

→ **본 실행 = 2단계**: ① `--enrich-detail` (JSON enrich) → ② merge 파이프라인 재실행 (DB 반영).
→ `--enrich-detail` 단독 실행으로는 "확인 필요 2,242" 가 줄지 않음.

### 위험 발견 (보고)

| # | 발견 | 영향 |
|---|---|---|
| E정정 | `--enrich-detail` 는 JSON-only. DB 반영은 별도 파이프라인 | 본 실행 명세 2단계로 재정의 필요 |
| 신규 | `_extract_period_status_from_detail_table` 가 현 bizinfo 레이아웃 미매칭 | 매칭은 s_title 리스트가 담당 — 결과적으로 문제 X (90%) |
| 신규 | `status` 필드 — 상세에 진행상태 없음 → enrich 가 status 직접 변경 X | end_date 기반 다운스트림 `infer_status` 가 결정 |
| 관찰 | `organization` = "금융/내수/창업/수출/경영" = bizinfo **카테고리** 라벨 | 데이터 품질 백로그 후보 (블로킹 X) |

---

## B. Step 2 — DRY-RUN 10건 결과

방법: LATEST.md "방법 C" 채택 — `--dry-run` 플래그 부재로, 기존 함수(`fetch_detail` / `parse_bizinfo_dates`)를 import 한 별도 스크립트로 수행. **코드 패치 0 / DB·JSON 변경 0** (스크립트는 실행 후 삭제).
대상: `bizinfo_all.json` 선두 10건 (end_date 없음 + url 보유).

### 10건 처리 결과

| # | 기관(카테고리) | detail.period | end_date | 판정 |
|---|---|---|---|---|
| 1 | 금융 | 2026.05.18 ~ 2026.05.22 | 2026-05-22 | ✓ |
| 2 | 금융 | 2026.05.18 ~ 2026.05.22 | 2026-05-22 | ✓ |
| 3 | 금융 | 2026.05.18 ~ 2026.05.22 | 2026-05-22 | ✓ |
| 4 | 내수 | 2026.05.18 ~ 2026.05.29 | 2026-05-29 | ✓ |
| 5 | 금융 | 2026.05.18 ~ 2026.05.22 | 2026-05-22 | ✓ |
| 6 | 창업 | 2026.05.18 ~ 2026.06.30 | 2026-06-30 | ✓ |
| 7 | 수출 | **예산 소진시까지** | (없음) | ✗ 마감일 부재 |
| 8 | 경영 | 2026.05.18 ~ 2026.05.29 | 2026-05-29 | ✓ |
| 9 | 경영 | 2026.05.19 ~ 2026.06.02 | 2026-06-02 | ✓ |
| 10 | 수출 | 2026.05.18 ~ 2026.05.29 | 2026-05-29 | ✓ |

### 집계

| 항목 | 값 |
|---|---|
| fetch 성공 | **10/10** (네트워크 실패 0) |
| end_date 추출 성공 | **9/10** |
| **매칭률** | **90%** |
| 실패 사유 | 1건 (#7) — 공고 자체에 마감일 없음 ("예산 소진시까지"). 파싱 버그 X |
| 기관 다양성 | 5종 (금융/내수/창업/수출/경영 — 카테고리 기준) |

### 실패 사례 분석 (#7)

- `신청기간` 라벨 값 = "예산 소진시까지" → 날짜 토큰 0개 → end_date 빈 값
- `period_html_grep` 에는 "2026.05.18~2026.05.29" 존재했으나, 우선순위상 라벨 값(s_title)이 grep 보다 우선이라 미채택
- → **진짜 마감일 없는 공고** = AI fallback 또는 grep 보조 후보 (정규식 버그 아님)

### 표본 편향 주의 (정직 보고)

- 선두 10건 = 최근 등록(2026.05.18~) **지자체 공고 위주**, "신청기간" 라벨 깔끔
- 시뮬이 우려한 KIAT/KICET 등 **국가기관 케이스 (10번째 정정)** 미포함
- → 90% 는 고무적이나 전체 1,433 row 매칭률과 다를 수 있음 → 본 실행 시 전체 재측정 필수

---

## C. Step 3 본 실행 권장 시점

매칭률 90% ≥ 80% → **본 실행 진입 조건 충족**.

단 위험 E 정정으로 본 실행 = 2단계 (JSON enrich → merge 파이프라인 DB 반영).

| 옵션 | 평가 |
|---|---|
| A. 5/20 시연 후 저녁 | 기술적으로 안전 (DB 직접 변경 X, `--out` 으로 JSON 보호 가능). 단 시연 + 박람회 피로 → **비권장** |
| **B. 5/22 차분히 (권장)** | ① 시연 당일 영향 0 ② JSON→DB merge 경로 (`merge_sources`/`run_pipeline`) 추가 확인 필요 ③ 표본 편향 → 본 실행 시 전체 매칭률 재측정 |

**권장: 옵션 B (5/22)**.

본 실행 wall clock 추정: 1,433 row × ~1.1s (HTTP fetch + sleep 0.12) ≈ **약 26분** (LATEST.md 50~70분 추정보다 짧음 — DB 가 아닌 JSON 1,433 row 대상이므로).

---

## D. 응모서 가치 — 사전 검증의 정량적 증거

> **30분 사전 작업 = 잘못된 멘탈모델 4건 직진 차단**
>
> 5/20 Step 1+2 사례 (12번째 정정):
> - 가설: `--enrich-detail` = DB 2,125 row UPDATE, 멱등성 `WHERE end_date IS NULL`
> - 실측: JSON-only 작업, DB 미접근, `--dry-run`·`--limit` 플래그 부재
> - 직진 시 사고: 존재하지 않는 `--dry-run` 으로 실행 → argparse 오류 / enrich 후 DB 안 바뀌어 디버깅 헤맴 / 없는 `WHERE` 조건 탐색
> - 코드 read 10분 = 위 사고 4건 사전 차단
>
> → 11번째 정정(시뮬)이 "코드 변경 0" 을 발견했고, 12번째 정정(코드 read)이 "실행 명세 자체가 틀림" 을 발견.
> → **"선 분석, 후 진행" 본능이 시뮬 → 코드 read 2단계로 작동한 누적 학습 증거.**

---

## 관련 파일

- 진입점: `docs/LATEST.md`
- 선행 시뮬: `docs/simulations/2026-05-19_phase3_poc_pre_simulation.md`
- 핵심 코드: `connectors/connector_bizinfo.py` (`fetch_detail` 168 / `_parse_detail_soup` 373 / `run_enrich_detail_from_file` 659)
- 날짜 파서: `pipeline/bizinfo_dates.py` (`parse_bizinfo_dates` 252)
- JSON→DB 경로: `pipeline/merge_sources.py` → `pipeline/run_pipeline.py`
