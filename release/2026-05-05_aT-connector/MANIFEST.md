# 배포확정: 2026-05-05 aT 한국농수산식품유통공사 커넥터 추가

## 마감 정보
- 마감일: 2026-05-05
- 작업자: 김형식
- v2 base commit: eca7394 (작업 직전)
- 검증 결과: 로컬 단독 실행 PASS (1차/2차 idempotency 확인)
- 백로그: 024

## 대상 사이트
- 이름: aT 한국농수산식품유통공사 글로벌
- URL: https://global.at.or.kr
- 목록 endpoint: POST `/front/bizReq/brList.do` (page 파라미터 1~25)
- 상세 endpoint: GET `/front/bizReq/brView.do?proj_id=...&proj_detail_id=...`
- 부처: 농림축산식품부 / 시행: 한국농수산식품유통공사 / 권역: 전국

## 변경 요약
정부 지원사업 수집 대상에 aT 글로벌 공고 200건을 신규 추가.
신규 커넥터 파일 1개 + 기존 `run_all.py`에 호출 등록 1줄.
다른 커넥터/공통 모듈/DB 스키마/의존성 무변경.

## 영향 파일 (2개)
- `connectors/connector_at_global.py` (신규, 204줄)
  - `parse_list_page`: BeautifulSoup4로 `table.boardList` 파싱, `goViewPage(proj_id, proj_detail_id)` 정규식 추출
  - `_map_status`: 진행중→접수중, 마감→마감
  - `collect_all_pages`: 1~25페이지 순회, 신규 0건 또는 빈 페이지 시 조기 종료
  - `save_to_db`: PRAGMA로 존재 컬럼만 동적 INSERT OR IGNORE (스키마 변경 없이도 컬럼 자동 매핑)
  - DB 경로: `__file__` 기준 `../db/biz.db` 자동 계산 → 폴더 어디서 실행해도 안전
- `run_all.py` (+1줄, 445행)
  - `run_connector("AT_GLOBAL", "connectors/connector_at_global.py")` 추가 (JBTP_RELATED 다음 줄, 기존 `run_connector(...)` 패턴 그대로)

## 검증 결과 (v2 메인 로컬)
**1차 실행** (clean baseline, AT 0건 상태):
```
[AT_GLOBAL] page  1~20: 각 10건
[AT_GLOBAL] page 21: 0건 → 종료
[AT_GLOBAL] DB 저장: 시도 200건, 신규 200건 (중복 0건)
[AT_GLOBAL] 완료: 수집 200건
```

**2차 실행** (idempotency 검증):
```
[AT_GLOBAL] page  1~20: 각 10건 (메모리 dedupe 신규 카운트)
[AT_GLOBAL] DB 저장: 시도 200건, 신규 0건 (중복 200건)
```
→ `idx_url` UNIQUE 인덱스 + `INSERT OR IGNORE` 정상 작동, 재실행 안전.

## DB 영향
- 총 건수: 11,722 → **11,922** (+200)
- AT 적재: 200건 (마감 192 / 접수중 8)
- source별 (신규 추가 후):
  - bizinfo 10,348 / jbexport 397 / jbbi 362 / kstartup 332 / **at_global 200** / jbtp 183 / jbtp_related 70 / unknown 30
- baseline 백업: `db/biz_pre_at_20260504.db` (md5 0516959b…, AT 적재 직전 상태)

## DB 스키마 영향
- **변경 없음**.
- `biz_projects` 테이블의 `idx_url` UNIQUE 인덱스를 활용 (기존 인덱스, 신규 생성 X).
- 커넥터가 쓰는 16개 필드 중 `region`/`summary`는 스키마에 없음 → `PRAGMA table_info` 동적 매핑이 자동 제외 (안전).

## 의존성
- **변경 없음** (`requirements.txt` 수정 X)
- 사용 패키지 모두 이미 설치됨:
  - `beautifulsoup4==4.14.3`
  - `requests==2.32.5`
  - `urllib3==2.6.3`

## 운영 영향
- `run_all.py --mode all` 또는 GitHub Actions 자동 크롤링 시 **AT_GLOBAL이 JBBI/JBTP/JBTP_RELATED 다음 순서로 자동 실행됨**.
- 수집은 평균 약 10초 (20페이지 × HTTP POST + 0.5s sleep).
- `subprocess.run` 타임아웃 300초 (run_all 기본값) 내 안전.
- 재실행 안전 (INSERT OR IGNORE로 중복 차단).
- 외부 HTTP: `https://global.at.or.kr` (SSL verify=False, urllib3 InsecureRequestWarning 억제).

## v1 적용 시 주의사항 (Phase 4 cherry-pick)
- v1의 `run_all.py`도 동일 구조 가정 (442~444 라인에 JBBI/JBTP/JBTP_RELATED 호출 패턴) → 호환성 높음
- 충돌 시 옵션:
  - `-X theirs` 자동 해결 (v2 변경 우선)
  - 수동 해결 (충돌 부위가 run_all.py 1줄이라 단순)
- v1 적용 후 검증: `py connectors/connector_at_global.py` 단독 실행 → "신규 N건" 또는 "중복 200건" 출력 확인
- Render 자동 재배포 필요 (push 후 약 5분)

## 의존성 (배포 순서)
- 없음 (단독 적용 가능, 다른 release와 충돌 없음)

## 롤백 방법
- `git revert <commit>` (1 commit 단위, 안전)
- 또는 수동: `connectors/connector_at_global.py` 삭제 + `run_all.py`의 `run_connector("AT_GLOBAL", ...)` 줄 제거
- DB 정리 (선택): `DELETE FROM biz_projects WHERE source='at_global'` 또는 `db/biz_pre_at_20260504.db`로 복원

## 알려진 이슈 / 향후 작업
- 상세 페이지 본문 미수집 (목록만, 사용자 의도). 향후 백로그 010(첨부 텍스트 시스템)과 연계 가능
- AT 사이트가 SSL 인증서 변경 시 `verify=False` 의존성 재검토 필요
- `MAX_PAGES=25`는 안전 상한 (현재 20). 200건 초과 시 갱신 필요

## 배포 상태
- [x] v2 로컬 검증 (단독 1차/2차 PASS)
- [ ] v2 push (사용자 수동, 대기)
- [ ] v1 cherry-pick (대기)
- [ ] v1 검증 (대기)
- [ ] v1 push (대기)
- [ ] Render 배포 확인 (대기)

## 산출물
- `MANIFEST.md` (본 문서)
- `DIFF.patch` (run_all.py +1줄 + connector_at_global.py 204줄 신규, intent-to-add 통합 patch)
- `connectors/connector_at_global.py` (신규 파일 사본, v2 메인과 md5 일치)
