# 064. 4개 connector url 정규화 — #1 scheduler 등록 사전조건

**상태**: 🟢 신규 (다음 사이클)
**발견일**: 2026-05-12 밤 (b029 sync dry-test 부수효과)
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
