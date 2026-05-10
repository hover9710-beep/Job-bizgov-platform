# 050. jbexport organization 추출 실패 (95% fallback)

**상태**: ✅ 완료 (2026-05-10) — release/2026-05-10_jbexport_org_fix/
**제안일**: 2026-05-10
**발견**: 백로그 049 작업 중 사이트 4위(oder=1543) 위젯 누락 사고 분석
**우선순위**: 높음 — 위젯 정확도 + 049 fix 완성도

## 현상

v1 DB jbexport 68건의 organization 분포 (049 직후):
- 66건 — `전북수출통합지원시스템` (fallback, 시스템명)
- 1건 — `(재)전북특별자치도 경제통상진흥원`
- 1건 — `코트라 전북지원본부`

→ 추출 성공률 1.5% (1/66, 코트라 1건은 별건). detail HTML 의 `td.th='주관기관'`
selector 가 백로그 032-1 (commit `a1c26b2`, 5/9) 에 도입되었지만 그 이전에 INSERT
된 row 들은 fallback 으로 남았고 이후 daily 가 돌아도 갱신되지 않음.

위젯에서는 임시 `organization='전북수출통합지원시스템'` 필터가 사용 중이라 fallback
row 만 위젯에 노출되고, 진짜 기관명이 추출된 row 는 차단됨 — 백로그 049 의 사이트
4위 (oder=1543, id=22915, organization='(재)') 누락이 그 결과.

## 진단 (Phase 2, 2026-05-10)

10건 sample detail HTML 검사:
- 모든 페이지에서 `td.th='주관기관'` 패턴 정확 작동 (10/10)
- selector 자체는 멀쩡 — 문제는 stale DB + 머지 로직 부재

```
id=4    extracted='(재)전북특별자치도 경제통상진흥원'  (DB: fallback)
id=27   extracted='한국무역협회 전북지역본부'            (DB: fallback)
id=49   extracted='(재)전북특별자치도 경제통상진흥원'  (DB: fallback)
...
id=4977 extracted='전북지방우정청'                     (DB: fallback)
```

## 근본 원인

`pipeline/update_db.py _upsert_one` UPDATE 절은 organization 을 row["organization"]
으로 그대로 덮음. detail fetch 일시 실패 / `JBEXPORT_FETCH_DETAIL_META=0` 환경변수
등으로 fallback 만 들어오면 DB 의 진짜 기관명을 fallback 으로 덮어쓰는 사고 가능.

049 의 `notice_chk`/`notice_order` 머지 패턴과 동일 구조.

## 해결안 (적용)

### 1. selector 보강 (방어)
`parse_jbexport_detail_html` 끝에 plain-text regex fallback 1개 추가 (3-layer th/dt/td.th
모두 실패한 경우 대비). 진단상 효과 0이지만 HTML 구조 변경 보험.

### 2. update_db organization 머지 로직 (핵심)
```python
_FALLBACK_ORGS = {"전북수출통합지원시스템", "기업마당"}

def _is_fallback_organization(v): ...

# _upsert_one UPDATE 직전:
merged_org = row["organization"]
if _is_fallback_organization(merged_org) and not _is_fallback_organization(old_org):
    merged_org = str(old_org or "").strip()
```

**효과**: 새 값이 fallback 이고 옛 값이 진짜 기관명이면 옛 값 보존. fetch 일시 실패
로 fallback 이 덮어쓰는 회귀 차단.

### 3. 위젯 organization 필터 제거 (옵션 A)
- 백로그 032 의 jbbi 332건 misclassification 은 이미 해결됨 (백로그 041 +
  자동 백필) — source='jbexport' 행은 100% url 도메인 jbexport.or.kr
- organization 임시 필터 제거. title 깨짐 차단(2종)만 유지

```sql
-- before
WHERE source='jbexport'
  AND organization='전북수출통합지원시스템'
  AND title NOT LIKE 'spSeq=%' AND title NOT IN ('공고 상세보기','MENU')

-- after
WHERE source='jbexport'
  AND COALESCE(TRIM(title),'') != ''
  AND title NOT LIKE 'spSeq=%' AND title NOT IN ('공고 상세보기','MENU')
```

### 4. 백필 (66 fallback → 진짜 기관명)
release/2026-05-10_jbexport_org_fix/backfill_organization.py:
- DB SHA256 백업 자동 생성
- 사이트 detail HTML 직접 호출 → selector → UPDATE
- safe-mode (only_fallback=True): 진짜 기관명 row 는 건너뜀

검증 결과:
```
total=66  fetched=66  fetch_error=0
extracted=66  extract_empty=0
updated_to_real=66
```

## 백필 후 분포 (총 68건)

| 건수 | 기관명 |
|---|---|
| 47 | (재)전북특별자치도 경제통상진흥원 |
| 6  | 코트라 전북지원본부 |
| 4  | 한국무역협회 전북지역본부 |
| 3  | 전주시 |
| 3  | 전북특별자치도 |
| 2  | 전북지방우정청 |
| 1  | 한국무역보험공사 전북지사 |
| 1  | 전주상공회의소 |
| 1  | (재)전북바이오융합산업진흥원 |

## 위젯 검증 — 사이트 1~5위 일치

```
1. notiChk=1 oder=1514 (재)전북특별자치도 경제통상진흥원   '온라인전시관 콘텐츠 제작지원'
2. notiChk=1 oder=1472 (재)전북특별자치도 경제통상진흥원   '제3차 무역사절단(미국 LA, 뉴욕)'
3. notiChk=0 oder=1544 (재)전북특별자치도 경제통상진흥원   'FTA통상진흥센터 설명회'
4. notiChk=0 oder=1543 (재)전북특별자치도 경제통상진흥원   'FTA통상진흥센터 5차 교육'  ← 049 누락 행 살아남
5. notiChk=0 oder=1542 한국무역협회 전북지역본부            '미주/유럽/중동 언택트 마케팅'
```

## 운영 적용

- 코드: 다음 push 시 Render 자동 재배포
- DB: 운영 Render Shell 에서 `python release/2026-05-10_jbexport_org_fix/backfill_organization.py`
- 알림 영향 0 (organization 컬럼만 UPDATE, diff_new url 기반 비교 무관)

## 관련

- 백로그 032-1 (5/9 commit a1c26b2): 첫 detail organization 추출 시도. selector 작동
  하지만 update_db 머지 로직 누락으로 stale 잔존
- 백로그 041 (5/8): infer_source 보강으로 jbbi misclassification 해결 → 050 옵션 A
  채택 가능해진 선행 조건
- 백로그 049 (5/10): 사이트 정렬 키 매핑 — 본 050 의 발견 계기
