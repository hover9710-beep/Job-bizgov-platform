# 배포확정: 2026-05-10 jbexport 위젯 정렬 정식 fix (백로그 049)

## 마감 정보
- 마감일: 2026-05-10
- 작업자: hover9710
- v1 base commit: `ef241d2` (작업 직전)
- v2 base commit: `6d6341f`
- 검증 결과: 로컬 v1 백필 + 위젯 SQL 검증 PASS
- 백로그: 049 (위젯 정렬), 034 (선행 시도 — 미반영 컬럼)

## 배경

`load_latest_by_source('jbexport', 5)` 위젯이 사이트 jbexport.or.kr 의
실제 게시 순서와 어긋나는 문제. 백로그 034 가 `notice_create_dt`(epoch ms)
컬럼을 추가했지만 `pipeline/update_db.py` 의 `_prepare_row` /
`_upsert_one` 이 해당 키를 INSERT/UPDATE 컬럼 목록에 넣지 않아 **컬럼은
존재하지만 모든 행 NULL** — 사실상 정렬 무력화 상태였음.

사용자 진단 (raw JSON 5건 검증):
- 사이트 정렬 = 1차 `notiChk DESC` (공지 핀), 2차 `oder DESC` (등록 연번)
- 사이트 1~5번: notiChk=1 oder=1514 / 1472, notiChk=0 oder=1544 / 1543 / 1542

## 변경 요약

DB 스키마에 `notice_chk` (INTEGER DEFAULT 0), `notice_order` (INTEGER DEFAULT 0)
2개 컬럼 추가. 크롤러는 list API 응답의 `notiChk` / `oder` 를 추출해 dict 에
실어 보내고, `update_db._upsert_one` 이 INSERT/UPDATE 시 두 컬럼을 같이 저장.
위젯 SQL 의 ORDER BY 를 `notice_chk DESC, notice_order DESC` 매핑으로 교체.

기존 68 jbexport 행은 백필 스크립트로 일괄 채움 (사이트 list API 1회 호출).

## 영향 파일 (코드 v1/v2 동시)

### `appy.py`
- `_init_db`: `_ensure_column(... "notice_chk" INTEGER DEFAULT 0)` 추가, 동일하게 `notice_order` 추가
- `load_latest_by_source` jbexport 분기: ORDER BY 를
  ```sql
  ORDER BY COALESCE(notice_chk, 0) DESC,
           COALESCE(notice_order, 0) DESC,
           COALESCE(created_at, '') DESC, id DESC
  ```
  로 변경. 기존 `COALESCE(notice_create_dt, 0) DESC` 는 제거 (전체 NULL 이라 의미 없음).

### `pipeline/jbexport_daily.py`
- `extract_announcement(row)`: list API 응답의 `notiChk` / `oder` 를 정수로
  파싱해 out dict 에 `notice_chk` / `notice_order` 키로 추가. NULL/빈값/오타이면 0.

### `pipeline/update_db.py`
- `_init_db`: `_ensure_column` 헬퍼가 `INTEGER DEFAULT 0` 화이트리스트 미통과라
  직접 `ALTER TABLE biz_projects ADD COLUMN ...` 호출.
- `_prepare_row`: row dict 에 `notice_chk` / `notice_order` 정규화 (int or 0).
- `_upsert_one`:
  - INSERT: 두 컬럼 같이 저장.
  - UPDATE: 새 값이 0(누락) 이면 기존 DB 값 보존하는 머지 — 다른 source upsert 가
    jbexport 행 정렬 키를 0 으로 덮는 사고 방지 (attachments_json/ai_summary 패턴 동일).

## 영향 파일 (배포 산출물 v1 only)

### `release/2026-05-10_jbexport_widget_sort/backfill_notice_order.py`
- DB SHA256 + 타임스탬프 백업 사본 생성 (백업 필수)
- 사이트 `getWork1Search.do` upstream 직접 호출 (work_year=2026 + 2025, length=200)
- SP_SEQ → DB url `LIKE '%spSeq=' || SP_SEQ` 매칭
- `notice_chk`, `notice_order` UPDATE
- 결과: rows_in_db / site_rows / matched / updated / no_seq_in_url / no_match_on_site

### `release/2026-05-10_jbexport_widget_sort/MANIFEST.md`
- 본 문서

## 검증 결과 (v1 로컬 DB)

```
[backfill] DB 경로: db/biz.db
[backfill] DB 백업: biz.db.backup_20260510_160330_049_widget_sort_fc950f53ca35
[backfill] work_year=2026 → 68건 (누적 68)
[backfill] work_year=2025 → 133건 (누적 201)
[backfill] 사이트 수집 완료: 201건
[backfill] add column: biz_projects.notice_chk (INTEGER DEFAULT 0)
[backfill] add column: biz_projects.notice_order (INTEGER DEFAULT 0)
[backfill] 결과:
  rows_in_db: 68
  site_rows: 201
  matched: 68
  updated: 68
  no_seq_in_url: 0
  no_match_on_site: 0
```

위젯 SQL 직접 실행 (백필 후, 변경된 ORDER BY 기준):
```
1. id=3672 notiChk=1 oder=1514  '2026년 수출통합지원시스템 온라인전시관 콘텐츠 제작지원 참여기업 모집'
2. id=3683 notiChk=1 oder=1472  '2026 제3차 무역사절단(미국 LA, 뉴욕) 참여기업 모집'
3. id=20283 notiChk=0 oder=1544 '[교육/컨설팅] 2026년 전북FTA통상진흥센터 설명회…'
4. id=12425 notiChk=0 oder=1542 '[온라인 마케팅] 2026년 미주/유럽/중동 언택트 마케팅 지원사업'
5. id=10061 notiChk=0 oder=1541 '[기타 지원사업] 2026년 전주시 AI 활용 디지털 마케팅 지원사업'
```

사용자 진단 5쌍 (notiChk, oder) DB 매칭: 5/5 OK
- 1514 → id=3672, 1472 → id=3683
- 1544 → id=20283, 1543 → id=22915, 1542 → id=12425

위젯 출력은 사이트 1, 2, 3, 5 위와 일치. 사이트 4위 (oder=1543, id=22915)는
기존 임시 `organization='전북수출통합지원시스템'` 필터에서 제외됨 — 해당 행
organization 이 detail HTML 추출 결과 `(재)전북특별자치도 경제통상진흥원`. 정렬
키 자체(049)는 정확하게 동작; 제외 사유는 별 트랙(아래 "알려진 이슈" 참조).

## DB 스키마 영향
- `biz_projects` 에 컬럼 2개 추가 (`notice_chk`, `notice_order`, INTEGER DEFAULT 0).
- 기존 컬럼·인덱스 무변경. NULL 허용 + DEFAULT 0 → 다른 source 행 영향 0.
- `notice_create_dt` 컬럼은 유지하되 ORDER BY 에서는 더 이상 사용 안 함 (전체 NULL).

## 의존성
- 변경 없음 (`requirements.txt` 수정 X)
- 백필 스크립트가 사용하는 패키지는 모두 기존: `requests`, `urllib3`.

## 운영 영향
- v1 로컬 DB는 사본 (`db/biz.db`). 운영 Render disk `/var/data/biz.db` 는
  별도. 본 백필은 **로컬 사본만** 갱신 — 운영 영향 0.
- 코드 변경 (`appy.py`, `pipeline/*.py`)은 git push 시 Render 자동 재배포 →
  운영에서도 다음 daily 부터 신규 jbexport 행에 `notice_chk` / `notice_order`
  채워짐. 운영 DB 백필은 별도 절차 필요 (백로그 033 의 운영 백필 메커니즘).
- 위젯 ORDER BY 변경은 운영 DB 백필 전에는 거의 효과 없음 (모든 행 0 → COALESCE
  → 사실상 created_at DESC 폴백). 백필 후 정상 작동.

## v1 ↔ v2 동기 상태
- v1 / v2 양쪽 모두 동일 코드 변경 적용.
- 로컬 DB 백필은 v1 만 실행 (현재 working dir). v2 로컬 DB 가 별도 갱신
  필요하면 `release/.../backfill_notice_order.py` 동일 스크립트 실행 가능.

## 롤백 방법
- 코드: `git revert <commit>` (v1/v2 각각 1 commit 단위)
- DB: `db/biz.db.backup_20260510_160330_049_widget_sort_fc950f53ca35` 로 복원
- 컬럼 자체 제거가 필요하다면 SQLite 는 DROP COLUMN 미지원 → 새 테이블 만들어
  복사 (드물게 필요). 보통 컬럼 무사용 상태로 두는 편이 안전.

## 알려진 이슈 / 향후 작업

### 1. 위젯 organization 임시 필터 (백로그 050 트랙)
`load_latest_by_source('jbexport')` 의 `organization='전북수출통합지원시스템'`
필터는 2026-05-07 임시 워크어라운드. jbbi 332 건이 source='jbexport' 로 잘못
분류된 상태에서 위젯 섞임을 막기 위함. 단점: detail HTML 에서 정상 추출된
다른 jbexport organization (예: `(재)전북특별자치도 경제통상진흥원`) 은 위젯에서 제외됨.
오늘 검증에서 사이트 4위 (oder=1543, id=22915) 가 이 필터에 걸려 빠짐. 백로그
050 (organization 추출 정합성) 의 phase 2~ 에서 정식 fix 예정.

### 2. 운영 DB 백필
운영 (Render) DB 는 본 release 의 백필 대상에 포함되지 않음. 운영 적용은
백로그 033 의 운영 백필 절차에 함께 묶어서 (또는 별도 Render shell 세션에서)
동일 `backfill_notice_order.py` 실행 필요.

### 3. notice_create_dt 컬럼 정리
백로그 034 가 추가했지만 사실상 무용 (전체 NULL). 신규 ORDER BY 에서는 미사용.
스키마에 남아있어도 무해하지만, 향후 정리 시 제거 가능 (DROP COLUMN 미지원이라
부담 있음 → 그대로 두는 편이 비용 효율적).

## 배포 상태
- [x] v1 로컬 코드 변경
- [x] v2 코드 변경
- [x] 로컬 v1 DB 백필 + 검증
- [ ] git commit (사용자 승인 후)
- [ ] git push v2 → Render 자동 배포
- [ ] git push v1 (있다면)
- [ ] 운영 DB 백필 (백로그 033 절차에 합쳐 진행)

## 산출물
- `MANIFEST.md` (본 문서)
- `backfill_notice_order.py` (DB 백업 + 사이트 호출 + UPDATE 백필 스크립트)
