# 064. 4개 connector url 정규화 — #1 scheduler 등록 사전조건

**상태**: 🟡 Phase 2 (3/4 connector 완료, kseafood Phase 2-B 잔존). #1 활성화 완료
**발견일**: 2026-05-12 밤 (b029 sync dry-test 부수효과)
**완료일**: 2026-05-12 한밤중 (3 connector + #1) / kseafood 잔존
**우선순위**: 높음 — #1 (run_all.py aux crawlers 자동 호출) 의 사전조건
**연관**: 029 (v1/v2 connector divergence), 057 (Phase 2.1f follow-up — jbtp url 정규화 surgical), 061 (전체 파이프라인 명세), 062 (E2E 파이프라인 hook)

## 한 줄

`connectors/{at_global, kseafood, jbbi, jbtp_related}` 4개 connector 가 jbtp 와 동일한 url 파라미터 순서 변경 결함 — 사이트가 a[href] 파라미터 순서 변경 시 `idx_url UNIQUE` 우회 → 중복 INSERT. #1 scheduler 자동 호출의 사전조건으로 4 connector 모두 url 정규화 fix 필요.

## 발견 경위

2026-05-12 밤 #1 (run_all.py 에 보조 5 connector 자동 호출 추가) dry-test:

```
[run_all] run_aux_crawlers() — 137 → ?
  jbtp:         137  → 137  (+0)    ← fd79792 fix 적용됨
  at_global:    203  → 409  (+206)  ← 사고
  kseafood:     244  → 489  (+245)  ← 사고
  jbbi:         369  → 741  (+372)  ← 사고
  jbtp_related: 71   → 141  (+70)   ← 사고
                                   합계 +893 row 잠재 중복
```

at_global 샘플 url 패턴 확인:
- 옛: `https://global.at.or.kr/front/bizReq/brView.do?proj_detail_id=0&proj_id=8182`
- 새: `https://global.at.or.kr/front/bizReq/brView.do?proj_id=7937&proj_detail_id=0`

→ 사이트가 url 파라미터 순서 변경 (jbtp 와 동일 패턴, 5/12 우연 발견). 4 connector 모두 동일 잠재 결함.

→ 즉시 백업 복원 (`db/biz.db.backup_b029_sync_pre_20260512_225334`, SHA256 매칭) + run_all.py 변경 되돌림 (`git checkout`). DB 손상 0.

## 본질

`connectors/_common.py` 의 `save_to_db()` 가 `INSERT OR IGNORE INTO biz_projects` + `idx_url UNIQUE` 에 의존. UNIQUE 가 url **string 매칭** 이라 같은 detail 의 url 파라미터 순서만 달라져도 중복 통과. 사이트 의도와 무관하게 발생 (Spring/Tomcat 등 백엔드 라이브러리 업데이트가 흔한 원인).

→ 사이트 변경에 대한 안정성을 connector 의 url 빌더가 책임져야 함 (jbtp 의 `_normalize_detail_url` 패턴).

## 사이트별 안정 키 (1차 진단 — 확인 필요)

| connector | 사이트 | 안정 키 후보 | 정규화 방법 |
|---|---|---|---|
| at_global | global.at.or.kr | `proj_id` + `proj_detail_id` (둘 다 필요할 가능성) | `_normalize_detail_url(href)` — query 파싱 후 표준 순서 |
| kseafood | biz.k-seafoodtrade.kr | `biz_data` (Base64 인코딩 idx — 디코드 후 안정 키 확인 필요) | Base64 디코드 → idx 추출 → 새 url 생성 |
| jbbi | jif.re.kr | `dataSid` + `menuUUID` (jbexport 와 유사 패턴) | jbtp 와 유사한 query 정규화 |
| jbtp_related | jbtp.or.kr | `dataSid` (jbtp 와 같은 사이트) | **jbtp 의 `_normalize_detail_url` 재사용 가능** (다만 BBS_0000007, menuCd 다름) |

## 진행 방식

### Phase 1 — connector 별 url 패턴 분석 (자율, 30~60분)

각 connector 의 `parse()` / `parse_list_page()` 에서:
1. 사이트가 만들어주는 a[href] 형식 (현재 시점)
2. 옛 row 의 url 형식 (DB 에 저장된 것)
3. 안정 키 (사이트 url 변경에도 같은 detail 가리키는 부분)

→ 각 connector 의 정규화 함수 시그니처 + 표준 url 형식 확정

### Phase 2 — 각 connector 에 정규화 함수 추가 (자율, 30~60분 × 4)

jbtp 의 `_normalize_detail_url` 패턴 따름:

```python
_KEY_RE = re.compile(r"<안정 키 정규식>")

def _normalize_detail_url(href: str) -> str:
    m = _KEY_RE.search(href or "")
    if not m:
        return urljoin(BASE, href)
    return f"{BASE}<표준 path>?<표준 query 순서>"
```

각 connector 의 `parse()` 또는 `normalize()` 의 url 빌더에서 본 함수 호출.

### Phase 3 — dry-test 검증 (자율, 10분)

각 connector 단독 실행 후 DB count 변동 확인:
- BEFORE: `SELECT COUNT(*) FROM biz_projects WHERE source=<src>`
- AFTER: 신규 INSERT 0 (옛 row 와 url string 매칭) 또는 사이트 신규 분만큼만 +N

만약 여전히 +N 대량 발생 시 정규화 미흡 → 재진단.

### Phase 4 — #1 scheduler 등록 재시도

4 connector fix 완료 후 #1 의 `run_aux_crawlers()` 자동 호출 재적용 + 다시 dry-test.

## 검증 데이터

- 백업: `db/biz.db.backup_b029_sync_pre_20260512_225334` (SHA256: `e6152756a901e993`, sync 직전 상태)
- 백업 시점 source 별 count: at_global=203, jbbi=369, jbtp=137, jbtp_related=71, kseafood=244

## 정책 시사점 (백로그 061/062 와 연관)

| 항목 | 시사 |
|---|---|
| connector UNIQUE 키 | url string 매칭은 사이트 url 변경에 취약. **`(source, 안정 키) UNIQUE` 인덱스 신설** 검토 (장기) |
| dry-test 가치 입증 | run_aux_crawlers 첫 실행이 자동 호출 전이라 사고 사전 발견. 백로그 062 (E2E hook) 가 본 사이클에서 가치 입증 |
| 사이트 url 변경 모니터링 | 5/12 jbtp 우연 발견. 다른 사이트는 언제부터 결함이었는지 모름 — Phase 1 진단에서 시점 추적 필요 |
| `_common.save_to_db` 한계 | INSERT OR IGNORE + idx_url UNIQUE 패턴이 connector 마다 안정 키 다른 사이트에 일률 적용 위험. 본 백로그 완료 후 _common 자체 강화 검토 |

## 메모

- 본 백로그는 **#1 scheduler 등록의 사전조건**. 064 완료 전 #1 적용 시 자동 893 row 사고 위험
- 029 통째 sync (jbtp 만) 는 이미 commit `fd79792` 로 완료 — jbtp 는 본 백로그 대상 외
- 사용자 명시: ADMIN_KEY 회전 권고 항목은 본 작업 보고에서 제외 (memory `feedback-admin-key-rotation`)

---

# 실행 결과 (2026-05-12 한밤중)

## Phase 1 진단 결과

| connector | 옛 DB url 패턴 | 현재 connector 빌드 | Fix 방식 |
|---|---|---|---|
| at_global | `proj_detail_id=0&proj_id=8182` (203건 동일) | `proj_id=...&proj_detail_id=...` | 빌드 순서 1줄 변경 |
| jbtp_related | `boardId=BBS_0000007&...&dataSid=...&menuCd=DOM_...` (71건) | `menuCd=...&boardId=...&dataSid=...` | 빌드 순서 1줄 변경 (jbtp 와 동일 패턴) |
| jbbi | `boardArticleUUID=...&boardUUID=...&categoryGroup=0&menuUUID=...&page=1&rowCount=10` (369건, 알파벳 순) | dict 정의 순 (`boardUUID, menuUUID, boardArticleUUID, ...`) | `urlencode(q)` 의 dict 키 알파벳 순으로 정렬 |
| kseafood | `?biz_data=<Base64(idx=N&startPage=X&listNo=Y&table=cs_biz&...)>%7C%7C` (244건, 페이지마다 다른 startPage/listNo) | 사이트 a[href] 그대로 urljoin (full string 그대로) | **본질 다름** — Base64 안에 페이지 컨텍스트 포함, 같은 detail 도 클릭 페이지마다 다른 string. Phase 2-B 별도 처리 |

## Phase 2 — 3 connector 정규화 적용 (commit `9b9398a`)

### 변경
| 파일 | 변경 |
|---|---|
| `connectors/connector_at_global.py` | url 빌드 1줄 (`proj_detail_id` 먼저) |
| `connectors/connector_jbtp_related.py` | url 빌드 1줄 (`boardId` 먼저) |
| `connectors/connector_jbbi.py` | `build_view_url()` 의 dict 키 알파벳 순 정렬 |

### 단독 검증 (각 connector 1회 실행)

| connector | BEFORE | AFTER | 사이트 실제 신규 |
|---|---|---|---|
| at_global | 203 | 206 | +3 |
| jbtp_related | 71 | 72 | +1 |
| jbbi | 369 | 372 | +3 |

→ 옛 row 와 url string 매칭 성공 (중복 INSERT 0). 사이트 실제 신규 분만 +N.

## #1 scheduler 등록 활성화 (commit `9b9398a`)

`run_all.py` 에 `run_aux_crawlers()` 추가:
- 4 connector (jbtp / jbbi / at_global / jbtp_related) non-fatal 자동 호출
- master 3종 (jbexport / bizinfo / kstartup) 실패는 fatal 유지 (기존 정책)
- kseafood 는 Phase 2-B 후 추가 예정

### 통합 dry-test (run_aux_crawlers 2회 연속 실행)

| connector | 1차 실행 | 2차 실행 |
|---|---|---|
| jbtp | 137 (+0) | 137 (+0) |
| jbbi | 372 (+0, 1차에서 이미 +3) | 372 (+0) |
| at_global | 206 (+0, 1차에서 이미 +3) | 206 (+0) |
| jbtp_related | 72 (+0, 1차에서 이미 +1) | 72 (+0) |

→ **idempotent 검증 PASS**. 매일 daily run 시 사이트 실제 신규 분만 INSERT, 옛 row 중복 0.

## Phase 2-B — kseafood 별도 처리 (잔존)

### 본질
사이트가 `biz_data` Base64 안에 페이지 컨텍스트 (`startPage`, `listNo`) 를 포함:
- 같은 idx=100522 detail 도 page1 클릭 vs page2 클릭 시 다른 Base64 → 다른 url string
- 옛 244 row 의 url 모두 다른 페이지 컨텍스트 — 통일 형식 없음

### 진행 방향 (다음 사이클)

| 단계 | 내용 |
|---|---|
| 2-B1 | 옛 244 row 의 url 을 모두 idx-only 표준 url 로 백필 (`?biz_data=<Base64(idx=N)>%7C%7C` 또는 `?idx=N` 직접). 표준 형식 결정 |
| 2-B2 | `connector_kseafood.py` 의 `full_url` 빌드를 표준 형식으로 변경 |
| 2-B3 | dry-test 후 동일하게 변동 0 검증 |
| 2-B4 | Render sync 으로 운영 DB 244 row UPDATE |
| 2-B5 | `run_all.py` 의 `run_aux_crawlers()` 에 kseafood 추가 |

### 우선순위
中 — kseafood 는 위젯 후순위 source (백로그 053 메모 참조). #1 의 다른 4 connector 가 자동화되면 마스터 흐름 회복. 다만 kseafood 의 신규 row 가 매주 ~5건 발생 가능성 — 단기 모니터링 위해 수동 실행 또는 별도 사이클.

## 사고 회고 (이번 사이클)

본 사이클 사고 0회. dry-test 가 자동 호출 활성화 전 사고 사전 발견 → 백로그 062 가치 입증. 사이클 분리 (064 → #1) 가 안전성 보장.

## 정책 시사점 (백로그 061/062 연관)

1. **connector url 빌드 패턴 표준화** — 사이트가 a[href] 변경하더라도 connector 가 안정 키 (id/uuid) 만 추출해 자체 빌드 시 회피 가능
2. **dict 키 순서 의존**: Python 3.7+ dict 가 insertion order 유지 → 의도치 않게 url string 달라짐. **알파벳 순 또는 `sorted(q.items())` 표준** 검토
3. **사이트 url 변경 시점 미상**: 5/12 우연 발견. 다른 connector (bizinfo, kstartup) 도 동일 잠재 — 점검 필요 (별도 백로그)
4. **사이트 url 디자인 가변성**: kseafood 처럼 Base64 + 페이지 컨텍스트 패턴은 url string 매칭 불가능 — DB 스키마 차원에서 `(source, 안정 키) UNIQUE` 인덱스 검토 (장기)
