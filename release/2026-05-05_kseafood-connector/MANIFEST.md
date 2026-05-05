# 배포확정: 2026-05-05 한국수산회 K-Seafood Trade 커넥터 추가

## 마감 정보
- 마감일: 2026-05-05
- 작업자: 김형식
- v2 base commit: a60fd21 (작업 직전)
- 검증 결과: AT 전용 폴더 + v2 메인 양쪽에서 1차/2차 idempotency PASS
- 백로그: 025

## 대상 사이트
- 이름: 한국수산회 K-Seafood Trade
- URL: https://biz.k-seafoodtrade.kr
- 목록 endpoint: GET `/apply/export_list.php` (페이지 1) / GET `?biz_data=<Base64(startPage=N&...)>||` (페이지 2~)
- 상세 endpoint: GET `/apply/export_view.php?biz_data=<Base64>||` (수집 안 함, 목록만)
- 페이지 단위: 20건, 총 14페이지 (244건 + AT 24건 = 268건)
- 부처: 해양수산부 / 시행: 수행기관 컬럼 그대로 (수협중앙회/한국수산회/한국수산무역협회) / 권역: 전국

## 변경 요약
정부 지원사업 수집 대상에 한국수산회 K-Seafood Trade 공고 244건을 신규 추가.
백로그 024(AT) 사이트의 외부 링크 형태로 노출되는 aT 사업(수행기관=한국농수산식품유통공사)은 중복 방지를 위해 수집 단계에서 skip.
신규 커넥터 파일 1개 + 기존 `run_all.py`에 호출 등록 1줄.
다른 커넥터/공통 모듈/DB 스키마/의존성 무변경.

## 영향 파일 (2개)
- `connectors/connector_kseafood.py` (신규, 213줄)
  - `parse_list_page`: BeautifulSoup4로 `table > tbody > tr` 파싱, 4-td 구조 (상태/사업명/모집기간/수행기관)
  - `_extract_idx`: 상세 href의 `biz_data` Base64 디코딩 → `idx` 추출 → in-memory dedup 키
  - `_make_page_biz_data`: 페이지네이션 Base64 생성 (`startPage=N&listNo=...` 인코딩 + `||` suffix)
  - `_map_status`: 모집중/접수중→접수중, 마감/종료→마감 (AT 커넥터와 표기 통일)
  - **AT-skip**: `td[3]` 수행기관에 "한국농수산식품유통공사" 포함 시 skip (백로그 024와 중복 방지)
  - `collect_all_pages`: 1~30페이지 순회, 빈 tbody 또는 신규 0건 시 조기 종료
  - `save_to_db`: PRAGMA로 존재 컬럼만 동적 INSERT OR IGNORE (스키마 변경 없이도 컬럼 자동 매핑)
  - DB 경로: `__file__` 기준 `../db/biz.db` 자동 계산
- `run_all.py` (+1줄, 446행)
  - `run_connector("KSEAFOOD", "connectors/connector_kseafood.py")` 추가 (AT_GLOBAL 다음 줄, 기존 `run_connector(...)` 패턴 그대로)

## 사이트 진단 결과 (Phase 1 발견사항)
- ⚠️ 사용자 사전 분석의 `?page=N` 페이지네이션은 **무시됨** (page=2도 page=1과 동일 응답)
- 실제 작동: `?biz_data=<Base64>` 파라미터만 작동 (Base64 안에 startPage 인코딩)
- "aT 수출지원 모집공고" 카테고리 탭은 외부 링크 (`https://global.at.or.kr/...`로 redirect) → **수산회 사이트가 자체로 aT 데이터를 보유하지 않음**
- 그러나 수행기관 컬럼에 "한국농수산식품유통공사"가 24건 등장 → AT 커넥터(백로그 024)와 사업명 중복 가능성 → **수집 단계 skip 채택 (옵션 A)**
- 카테고리 부분 수집 (`?part_idx=1/3/6`)은 전체의 부분집합 → "전체" 한 번만 순회로 누락 없음

## 검증 결과 (v2 메인 로컬)
**1차 실행** (clean baseline, kseafood 0건 상태):
```
[KSEAFOOD] page  1: 수집 19건 (신규 19, AT-skip  1) / 누적 19건
[KSEAFOOD] page  2: 수집 17건 (신규 17, AT-skip  3) / 누적 36건
...
[KSEAFOOD] page 13: 수집 20건 (신규 20, AT-skip  0) / 누적 236건
[KSEAFOOD] page 14: 수집  8건 (신규  8, AT-skip  0) / 누적 244건
[KSEAFOOD] page 15: tbody 비어있음 → 종료

[KSEAFOOD] 수집 완료: 244건 (AT-skip 합계 24건)
[KSEAFOOD] 상태별: {'접수중': 8, '마감': 236}
[KSEAFOOD] 수행기관 분포 (상위 10):
    103 | 수협중앙회
    102 | 한국수산회
     39 | 한국수산무역협회
[KSEAFOOD] DB 저장: 시도 244건, 신규 244건 (중복 0건)
```

**2차 실행** (idempotency 검증):
```
[KSEAFOOD] DB 저장: 시도 244건, 신규 0건 (중복 244건)
```
→ `url` UNIQUE 인덱스 + `INSERT OR IGNORE` 정상 작동, 재실행 안전.

## DB 영향
- 총 건수: 11,922 → **12,166** (+244)
- KSEAFOOD 적재: 244건 (마감 236 / 접수중 8)
- AT 사업 skip: 24건 (백로그 024와 중복 방지, 사이트 원본 268건 중)
- source별 (신규 추가 후):
  - bizinfo 10,348 / jbexport 397 / jbbi 362 / kstartup 332 / **kseafood 244** / at_global 200 / jbtp 183 / jbtp_related 70 / unknown 30
- baseline 백업: `db/biz_pre_kseafood_20260505.db` (md5 FBE07074669BD738372149A1F5ED86EE, kseafood 적재 직전 상태)

## 수행기관 분포 (신규 244건)
| 수행기관 | 건수 | 비고 |
|---|---|---|
| 수협중앙회 | 103 | |
| 한국수산회 | 102 | 사이트 운영주체 |
| 한국수산무역협회 | 39 | |
| (한국농수산식품유통공사) | 24건 skip | AT 커넥터(백로그 024)와 중복 방지 |

## DB 스키마 영향
- **변경 없음**.
- `biz_projects` 테이블의 기존 `url` UNIQUE 인덱스 활용.
- 커넥터가 쓰는 17개 필드 중 `region`/`summary`/`kseafood_idx`는 스키마에 없을 수 있음 → `PRAGMA table_info` 동적 매핑이 자동 제외 (안전).

## 의존성
- **변경 없음** (`requirements.txt` 수정 X)
- 사용 패키지 모두 이미 설치됨:
  - `beautifulsoup4==4.14.3`
  - `requests==2.32.5`
  - `urllib3==2.6.3`
  - `base64` (표준 라이브러리)

## 운영 영향
- `run_all.py --mode all` 또는 GitHub Actions 자동 크롤링 시 **KSEAFOOD가 AT_GLOBAL 다음 순서로 자동 실행됨**.
- 수집은 평균 약 8초 (14페이지 × HTTP GET + 0.5s sleep).
- `subprocess.run` 타임아웃 300초 (run_all 기본값) 내 안전.
- 재실행 안전 (INSERT OR IGNORE로 중복 차단).
- 외부 HTTP: `https://biz.k-seafoodtrade.kr` (SSL verify=False, urllib3 InsecureRequestWarning 억제).

## v1 적용 시 주의사항 (Phase 5 cherry-pick)
- v1의 `run_all.py`도 동일 구조 가정 → 호환성 높음 (백로그 024 적용 후 line 445에 AT_GLOBAL 등록되어 있을 것)
- 충돌 시 옵션:
  - `-X theirs` 자동 해결 (v2 변경 우선)
  - 수동 해결 (충돌 부위가 run_all.py 1줄이라 단순)
- v1 적용 후 검증: `py connectors/connector_kseafood.py` 단독 실행 → "신규 244건" 또는 "중복 244건" 출력 확인
- Render 자동 재배포 필요 (push 후 약 5분)

## 의존성 (배포 순서)
- 백로그 024(AT 커넥터)가 v1에 먼저 적용되어 있어야 합니다 (run_all.py에 AT_GLOBAL 라인 존재 가정). 미적용 상태라면 KSEAFOOD 라인은 단독 작동하지만, AT-skip 24건이 KSEAFOOD가 아니라 어디에서도 수집되지 않게 됨.
- AT가 v1에 적용되어 있다면: 단독 적용 가능, 다른 release와 충돌 없음.

## 롤백 방법
- `git revert <commit>` (1 commit 단위, 안전)
- 또는 수동: `connectors/connector_kseafood.py` 삭제 + `run_all.py`의 `run_connector("KSEAFOOD", ...)` 줄 제거
- DB 정리 (선택): `DELETE FROM biz_projects WHERE source='kseafood'` 또는 `db/biz_pre_kseafood_20260505.db`로 복원

## 알려진 이슈 / 향후 작업
- 상세 페이지 본문 미수집 (목록만, 사용자 의도). 향후 백로그 010(첨부 텍스트 시스템)과 연계 가능
- 사이트 SSL 인증서 변경 시 `verify=False` 의존성 재검토 필요
- `MAX_PAGES=30`은 안전 상한 (현재 14). 600건 초과 시 갱신 필요
- period_text 파싱 빈값 1건 (244건 중 0.4%): `20250225 00시~20250307 23시` (구식 하이픈 없는 형식, 1년 전 마감 사업, 사용자 영향 없음 → 그대로 둠)
- AT-skip 정책은 사이트 운영 변화에 따라 재검토 필요 (현재 수산회가 게시하는 aT 사업은 백로그 024 AT 커넥터에서 직접 수집 중이라 가정)

## 배포 상태
- [x] AT 전용 폴더 검증 (단독 1차/2차 PASS, 244건)
- [x] v2 메인 로컬 검증 (단독 1차/2차 PASS, 244건)
- [ ] v2 push (사용자 수동, 대기)
- [ ] v1 cherry-pick (대기)
- [ ] v1 검증 (대기)
- [ ] v1 push (대기)
- [ ] Render 배포 확인 (대기)
- [ ] 필터 UI 추가 (Phase 7, Cursor 작업 끝난 후)

## 산출물
- `MANIFEST.md` (본 문서)
- `DIFF.patch` (run_all.py +1줄 + connector_kseafood.py 213줄 신규, intent-to-add 통합 patch, 305줄)
- `connectors/connector_kseafood.py` (신규 파일 사본, v2 메인과 md5 일치: 5D8F43905226EEB04E152A05F423E53C)
