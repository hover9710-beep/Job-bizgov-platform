# 배포확정: 2026-05-10 jbexport organization 추출 정상화 (백로그 050)

## 마감 정보
- 마감일: 2026-05-10
- 작업자: hover9710
- v1 base commit: `db32bfd` (049 직후)
- v2 base commit: `02d48f2` (049 직후)
- 검증 결과: v1 로컬 백필 (66/66 OK) + 위젯 SQL 사이트 1~5위 정확 일치 PASS
- 백로그: 050 (organization 추출), 032-1 (선행 시도 — 부분 작동)
- 의존: 049 release (notice_chk/notice_order 컬럼) — 위젯 ORDER BY 가 그 컬럼을 사용

## 배경

`load_latest_by_source('jbexport')` 위젯이 organization='전북수출통합지원시스템'
필터를 임시로 사용 중이었음 (2026-05-07, 백로그 032 jbbi 332건 misclassification 회피용).
백로그 049 (사이트 정렬 키) 적용 후 사이트 4위 (oder=1543) 가 이 필터에 걸려 빠지는
사고 노출 — DB organization='(재)전북특별자치도 경제통상진흥원' 으로 정확 추출되었지만
fallback 만 통과시키는 정책 때문에 차단됨.

진단 결과:
- v1 DB jbexport 68건 organization 분포: fallback 66건 / (재) 1건 / 코트라 1건 (1.5% 추출 성공)
- detail HTML selector 자체는 7~10건 sample 100% 작동 — fallback row 들은
  백로그 032-1 (selector 추가, commit `a1c26b2`) **이전** 에 INSERT 된 stale 상태
- selector 적용 후 daily 가 도는데도 organization 갱신 안 된 이유는 update_db 의
  머지 로직 부재 — fetch 일시 실패 / 환경변수 비활성 등으로 fallback 만 들어오면
  DB 의 진짜 기관명을 fallback 으로 덮어쓰는 구조

백로그 049 의 `notice_chk`/`notice_order` 머지 패턴과 동일.

## 변경 요약

1. detail HTML selector chain 끝에 plain-text regex fallback 1개 추가 (방어)
2. update_db._upsert_one 에 organization 머지 로직 추가 (fallback 새 값이면 옛 진짜 값 보존)
3. 위젯 jbexport 분기 organization 필터 제거 (옵션 A) — source='jbexport' = url 도메인
   jbexport.or.kr 100% 일치라 추가 필터 불필요
4. 65건 fallback row 백필 — detail HTML 호출 → organization 추출 → UPDATE

## 영향 파일 (코드 v1/v2 동시)

### `pipeline/jbexport_daily.py`
`parse_jbexport_detail_html` 끝에 organization 전용 regex fallback 추가:

```python
if not out["organization"]:
    m = re.search(
        r"(?:사업주관기관|사업수행기관|주관기관|수행기관|담당기관|지원기관)\s*[:：]?\s*([^\n\r<]+?)(?:\n|<|$)",
        full_text, re.IGNORECASE,
    )
    if m and ...:  # JS 잡음/길이/label 재포함 방어
        out["organization"] = cand
```

### `pipeline/update_db.py`
- `_FALLBACK_ORGS` 셋 + `_is_fallback_organization()` 헬퍼 신규
- `_upsert_one` SELECT 절에 organization 추가
- 머지: `if _is_fallback_organization(merged_org) and not _is_fallback_organization(old_org): merged_org = old_org`
- UPDATE 가 row["organization"] 대신 merged_org 사용

### `appy.py` `load_latest_by_source` jbexport 분기
- `AND organization = '전북수출통합지원시스템'` 필터 제거
- params 에서 fallback 값 제거 (title 깨짐 차단 ?, ? 만 남김)
- ORDER BY 는 049 와 동일 (notice_chk DESC, notice_order DESC, ...)

## 영향 파일 (배포 산출물)

### `release/2026-05-10_jbexport_org_fix/backfill_organization.py`
- DB SHA256 + 타임스탬프 백업 자동 생성
- 사이트 detail HTML 직접 호출 → selector 추출 → organization UPDATE
- safe-mode (BACKFILL_ONLY_FALLBACK=1, default): organization='전북수출통합지원시스템' 행만
- 멱등성: 같은 결과면 건너뜀, 새 값이 fallback 인데 옛이 진짜면 보존
- 기대: extracted=66/66, updated_to_real=66

### `release/2026-05-10_jbexport_org_fix/MANIFEST.md`
- 본 문서

## 검증 결과 (v1 로컬 DB, 2026-05-10 16:27)

```
[backfill] DB 백업: biz.db.backup_20260510_162758_050_org_fix_582aa6e616dd
[backfill] 대상 row: 66건
[backfill] 결과:
  total: 66
  fetched: 66
  fetch_error: 0
  extracted: 66
  extract_empty: 0
  updated_to_real: 66
  kept_existing_real: 0
  no_change: 0
```

백필 후 organization 분포 (총 68건):
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

위젯 SQL 출력 (옵션 A 적용 후, jbexport 5건):
```
1. id=3672  notiChk=1 oder=1514  org=(재)전북특별자치도 경제통상진흥원  '온라인전시관 콘텐츠 제작지원'
2. id=3683  notiChk=1 oder=1472  org=(재)전북특별자치도 경제통상진흥원  '제3차 무역사절단(미국 LA, 뉴욕)'
3. id=20283 notiChk=0 oder=1544  org=(재)전북특별자치도 경제통상진흥원  'FTA통상진흥센터 설명회'
4. id=22915 notiChk=0 oder=1543  org=(재)전북특별자치도 경제통상진흥원  'FTA통상진흥센터 5차 교육'
5. id=12425 notiChk=0 oder=1542  org=한국무역협회 전북지역본부          '미주/유럽/중동 언택트 마케팅'
```

→ 사이트 jbexport.or.kr 1~5위와 정확 일치 (049 미해결이었던 4위 oder=1543 도 정상 노출).

## DB 스키마 영향
- 변경 없음. 기존 `organization` TEXT 컬럼만 갱신.

## 의존성
- 변경 없음 (`requirements.txt` 수정 X). `requests`, `urllib3`, `bs4` 모두 기존.
- 049 release 의존 (notice_chk/notice_order 컬럼 — 위젯 ORDER BY 사용)

## 위젯 정책 결정 (Phase 6 — 사용자 채택: 옵션 A)
- A: organization 필터 제거 (✅ 채택). 단순. source='jbexport' = url 도메인 100% 일치
  라 추가 필터 불필요. 향후 misclassification 발생 시 그때 대응
- B: organization 화이트리스트 (9개 기관). 새 기관 추가 시 코드 수정 부담 → 미채택
- C: 기존 정책 유지 → 백필 후 위젯 0건 사고. 즉시 제거 필요 → 사실상 후보 아님

## 운영 영향
- v1 로컬 DB (`db/biz.db`) 만 백필 — 운영 Render disk 별도. 운영 적용은 별도 단계.
- 코드 변경 (appy.py, pipeline/*.py) 은 git push 시 Render 자동 재배포 → 위젯
  organization 필터 즉시 제거됨. 이 시점에 운영 DB organization 이 fallback 인 행도
  필터 제거로 위젯에 노출됨 (단순 fallback 문자열 포함). 따라서 **운영 DB 백필을
  코드 push 와 가깝게 진행** 하는 편이 사용자 시각 깔끔.
- 메일/알림 사고 위험 0: 백필은 organization 컬럼만 UPDATE — diff_new url 기반 비교
  영향 무, 메일 본문은 today.json 기반 영향 무 (백로그 033 패턴 비해당).

## 운영 백필 패키지
- `release/2026-05-10_jbexport_org_fix/backfill_organization.py` — Render Shell 에서
  `python release/.../backfill_organization.py` 직접 실행 가능 (env DB_PATH 자동 인식)
- `docs/render_sql/b050_followup.sql` — DB 백필 후 점검용 SQL (옵션, 분포 확인)

## 롤백 방법
- 코드: `git revert <commit>` (v1/v2 각 1 commit)
- DB: 백업 `biz.db.backup_20260510_162758_050_org_fix_582aa6e616dd` 로 복원
- 위젯 필터만 되돌리려면 appy.py 의 `extra_where` / params 에 한 줄씩 복원 가능

## 알려진 이슈 / 향후
1. **selector chain 4-layer 가 robust** — 백로그 032-1 의 3-layer 위에 regex fallback 추가
   되었으나, 진단 100% 통과로 실제 효과는 미미 (보험성). 단 jbexport 사이트 HTML
   구조 변경 시 1차 보호선
2. **운영 DB 백필** — Render 적용 별도 단계. push 와 가깝게 (5분 내) 권장
3. **백로그 032 (jbbi 332건 misclassification)** — 이미 해결됨 (백로그 041 commit
   a1c26b2 의 infer_source 수정 + 백필 자동 보정). 본 release 에서는 검증만 완료.

## 배포 상태
- [x] v2 코드 변경
- [x] v1 코드 변경 (cherry-pick: appy.py + jbexport_daily.py + update_db.py 각 surgical)
- [x] 로컬 v1 DB 백필 + 검증 (66/66 OK)
- [ ] git commit (사용자 승인 후)
- [ ] git push v2 + v1 → Render 자동 배포
- [ ] 운영 DB 백필 (Render Shell)

## 산출물
- `MANIFEST.md` (본 문서)
- `backfill_organization.py` (DB 백업 + 사이트 호출 + UPDATE 백필)
