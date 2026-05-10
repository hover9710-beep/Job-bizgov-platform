# 운영 위젯 ↔ 원본 사이트 정렬 진단/적용 표준 절차

## 1. 적용 대상

운영 위젯이 보여주는 source별 상위 N건과 원본 사이트의 표시 순서가
일치하지 않는 것이 의심될 때, 원인 진단 → DB 스키마/추출/위젯/백필 까지
이끄는 표준 절차.

최초 사례: 2026-05-10 jbexport 위젯 (백로그 049). 동일 패턴이 다른 source
(jbtp, jbbi, jbtp_related, kseafood, at_global 등)에서도 재현 가능.

## 2. 핵심 원칙

- **가설 금지, raw API 응답으로 확정 후 진행.** 사이트 화면 순서로
  "감"으로 정렬 컬럼을 짐작하지 않는다. 반드시 list API 의 raw JSON 5건을
  확보 → 후보 컬럼 값과 화면 순서가 매칭되는지 검증한 다음에야 코드를
  건드린다. (사용자 5/10 원칙: "가설로 가면 안 된다.")
- **1차/2차 정렬 분리 식별.** 대부분의 사이트는 단일 컬럼이 아니라
  `공지 고정 flag DESC, 등록 연번 DESC` 처럼 복합 정렬을 쓴다. 한 컬럼만
  맞춰 보고 일치한다고 판단하면 공지 핀 5건이 모두 같은 flag 값을 가질
  때 무너진다.
- **DB 백업 필수 (백필 시).** UPDATE 가 들어가는 단계 직전에 `.backup`
  파일 생성. v1/v2 모두 동일.
- **v1 surgical 만.** 신규 컬럼/파이프라인 변경은 v2 → release/ 또는
  v2 → v1 직접(단일 hunk surgical) 만 허용. v1 working tree 직접 작업
  금지.

## 3. 진단 절차 (Phase 0~4)

### Phase 0 — list API raw 응답 확보

해당 source 의 list API 호출 → 첫 5건의 raw 응답. **format 분기**
필수 — JSON 인지 HTML 인지 먼저 확인. 사이트가 `application/json`
응답이면 JSON 분기, `text/html` 이면 HTML 분기. proxy 가 필요한
사이트(jbexport 같은)는 `auto_run.bat` wrapper 또는 수동 proxy 기동 후
호출. proxy 무관 사이트(jbtp 같은 직접 HTML)는 `requests.get` 만으로 OK.

**JSON 사이트 패턴** (예: jbexport):

```python
# _check_<source>_raw.py  (.gitignore 차단 패턴, 사용 후 삭제)
import json, requests
r = requests.get("<LIST_ENDPOINT>", params={"start": 0, "length": 5}, timeout=30)
data = r.json()
items = data.get("data") or data.get("list") or data
print(json.dumps(items[:5], ensure_ascii=False, indent=2))
```

**HTML 사이트 패턴** (예: jbtp, jbbi):

```python
# _check_<source>_raw.py
import requests, re
from bs4 import BeautifulSoup
r = requests.get("<LIST_URL>", verify=False, timeout=15)
soup = BeautifulSoup(r.text, "html.parser")
for i, row in enumerate(soup.select("table tbody tr")[:6]):
    tds = row.select("td")
    classes = [t.get("class") for t in tds]      # tr.notice / td.notice 검사
    texts = [t.get_text(" ", strip=True) for t in tds]
    a = row.select_one("a")
    href = a.get("href", "") if a else ""
    # native ID 패턴 (dataSid, idx, no, seq 등)
    m = re.search(r"(?:dataSid|idx|no|seq)=(\d+)", href)
    print(f"[{i}] classes={classes} texts={texts} id={m.group() if m else None}")
```

HTML 사이트에서 후보 키:
- `tr.notice` / `td.notice` CSS class → 공지 flag
- URL 의 native ID (`dataSid`, `idx`, `no`, `seq`)
- td 인덱스의 등록일/연번 텍스트 (예: jbtp `td[0]` seq, `td[6]` 등록일)

출력 5~6건의 모든 td/필드를 한 번 훑는다. 다음 단계(후보 식별)의 입력.

### Phase 1 — 정렬 컬럼 후보 식별

raw 5건의 키 목록에서 다음 부류만 후보로 남긴다.

**포함**:
- 공지 고정 flag: `notiChk`, `notice_yn`, `top_yn`, `is_notice` 등 0/1
  또는 Y/N 값
- 등록 연번: `oder`, `no`, `seq`, `row_num`, `ord` 등 정수 (※ jbexport
  처럼 `order` typo 인 `oder` 형태 주의)
- 등록 timestamp: `create_dt`, `reg_dt`, `write_date` (단, 같은 batch
  로 들어온 행은 동일 ts 일 수 있어 1차 키로는 약함)

**제외**:
- `spSeq` 같은 UUID/hash (의미 없는 식별자)
- `view_count`, 조회수
- `end_dt`, 종료일

### Phase 2 — 5건 row 정렬 패턴 검증

후보 컬럼별로 raw 5건의 값을 표로 정리하고 사이트 화면 1~5번과 비교.

| 화면 위치 | 후보 A | 후보 B | 후보 C | ... |
|---|---|---|---|---|
| 1번 | ... | ... | ... | |
| 2번 | ... | ... | ... | |

`(후보 A DESC, 후보 B DESC)` 같은 복합 가설을 세우고 화면 5건이
**전부** 일치하는지 확인. 한 건이라도 어긋나면 가설 폐기 → 다른 컬럼
조합 재검토. 5/5 일치하면 확정.

### Phase 3 — DB 스키마 + 추출 + 위젯 + 백필

이 단계는 운영 DB 영향이 시작되는 분기점. v2 작업 → 검증 → v1 cherry-pick
→ Render 적용 순.

#### 3-1. ALTER TABLE 컬럼 추가

확정된 정렬 키를 DB 컬럼으로 매핑. **사용자 확인 후** 진행. 보통
`INTEGER DEFAULT 0` 안전. 적용 위치는 두 군데:

- `appy.py` `_init_db` — Flask 부팅 시 `_ensure_column` 으로 보장
- `pipeline/update_db.py` `_init_db` — pipeline 단독 실행 시 보장

#### 3-2. connector / pipeline 추출 추가

list API raw 응답의 키를 정수 정규화하여 out dict 에 담는다. 빈 값/
오타/None 모두 `0` 으로 떨어뜨려 ORDER BY 가 NULL 처리 분기에 빠지지
않게.

#### 3-3. appy.py 위젯 SQL ORDER BY 변경

해당 source 분기의 `ORDER BY` 를
`COALESCE(<1차 키>, 0) DESC, COALESCE(<2차 키>, 0) DESC, ...,
created_at DESC, id DESC` 로 교체.

#### 3-4. 기존 row 백필

ALTER 직후의 신규 컬럼은 모두 0/NULL — 사이트 정렬과 다시 어긋남.
list API 를 한 번 더 fetch 해서 spSeq(또는 동등한 PK) 매칭으로 UPDATE.

순서:
1. DB 백업 (`cp db/biz.db db/biz.db.bak.<timestamp>`)
2. list API 전체 fetch
3. spSeq → (notice_chk, notice_order) 맵 구성
4. 단일 트랜잭션 UPDATE
5. `no_match` 카운트 0 확인

#### upsert 머지 주의

다른 source 의 일상 upsert 가 jbexport 행 정렬 키를 `0` 으로 덮어쓰는
사고를 막아야 한다. `_upsert_one` 의 UPDATE 는
**"새 값이 0이고 기존 값이 0이 아니면 기존 보존"** 머지를 적용
(attachments_json / ai_summary 와 동일 패턴).

### Phase 4 — 운영 사이트 검증

1. v1 로컬 DB 에서 `appy.py` 의 위젯 query 직접 실행 → 결과 5개
2. 원본 사이트 1~5번과 비교 → 5/5 일치
3. 사용자가 v1 push, Render 적용
   - 운영 DB 컬럼 ALTER + 백필 SQL 은 별도 (`docs/render_sql/` 또는
     백로그별 SQL). 신규 컬럼은 ALTER 후 백필이 끝나기 전까지 정렬이
     무력 — 적용 순서를 미리 정해 둔다.

### 진단 카테고리 — 원인 분류

위젯 ↔ 사이트 불일치는 다음 세 카테고리로 떨어진다.

| 카테고리 | 원인 | 사례 | fix |
|---|---|---|---|
| **A 정렬 키 부재/오매핑** | DB 에 site 정렬 키 컬럼 없거나 ORDER BY 다른 키 사용 | 049 (jbexport notice_chk/notice_order), 053 (jbtp 동일) | 컬럼 추가 + ORDER BY 갱신 + 백필 |
| **B 필드 추출 정확도** | 정렬은 맞지만 다른 필드 (organization, title 등) 가 깨져서 위젯 필터/표시에 영향 | 050 (jbexport organization fallback), 035 (jbexport title detail) | selector 보강 + update_db 머지 보호 + 백필 |
| **C 위젯 필터에 의한 누락** | 위젯 SQL 의 WHERE 절 (`start_date >= X`, `status != ''`, `title NOT LIKE 'spSeq=%'`) 에 사이트 정상 row 가 걸려 탈락 | 053 (jbtp start_date 미추출 95/128 → `start_date >= '2026-01-01'` 탈락) | 추출 보강 + 백필 + (필요 시 위젯 WHERE 정책 검토) |

진단 시 카테고리를 먼저 식별하면 fix 범위가 결정된다. C 카테고리는
"정렬은 맞는데 row 가 안 보이는" 패턴 — start_date / status / 정상도
필터 의심.

## 4. 사례

### jbexport (2026-05-10, 백로그 049)

- **사이트**: `https://www.jbexport.or.kr` (proxy 경유 list API
  `http://127.0.0.1:5001/api/jbexport/list`)
- **확정 정렬 키**:
  - 1차: `notiChk DESC` (공지 핀)
  - 2차: `oder DESC` (등록 연번, `order` typo)
- **DB 컬럼 추가**: `notice_chk`, `notice_order`
  (둘 다 `INTEGER DEFAULT 0`)
- **추출 위치**: `pipeline/jbexport_daily.py:431-436`
  (`extract_announcement` 에서 `notiChk` / `oder` 정수 정규화)
- **upsert / 스키마**: `pipeline/update_db.py:100-114, 315-336,
  396-431, 460-486`
- **위젯 SQL**: `appy.py:880-909`
  (`load_latest_by_source` jbexport 분기 ORDER BY)
- **검증 5/5**:
  - `notiChk=1`: `oder=1514` (조회 912), `oder=1472` (조회 1320)
  - `notiChk=0`: `oder=1544`, `1543`, `1542`
- **위젯 ↔ 사이트 비교**: 사이트 1, 2, 3, 5, 6위 일치. 사이트 4위는
  기존 organization 임시 필터에 걸림 → 별건(백로그 050) 으로 분리.
- **백필**: v1 로컬 DB 68건 전수 매칭 UPDATE (`no_match=0`).
- **commit**: v2 `02d48f2` (`fix(jbexport): 위젯 정렬 키 notice_chk/
  notice_order 정식 매핑 (백로그 049)`). v1 push 는 사용자 직접
  처리 예정.
- **운영(Render) 적용**: ALTER + 백필 SQL 은 본 commit 범위 밖.
  적용 시 `docs/render_sql/b049_*.sql` 로 별도 작성 후 Render Shell
  에서 실행.
- **선행 사고**: 백로그 034 가 `notice_create_dt` (epoch ms) 컬럼을
  추가했지만 `update_db.py` 의 `_prepare_row` / `_upsert_one` 에 키가
  안 들어가 있어 모든 행 NULL → 사실상 정렬 무력 상태였음
  (`docs/daily/2026-05-08`). 049 는 정렬 키 자체를 사이트 기준
  (`notiChk` / `oder`) 으로 갈아탄 결정.

### jbexport organization 추출 (2026-05-10, 백로그 050)

- **카테고리**: B 필드 추출 정확도 (049 의 정렬 카테고리와 다름 —
  동일 source 의 다른 측면)
- **선행 상태**: 백로그 032-1 (5/8) selector
  (`table td.th="사업주관기관/사업수행기관/주관기관/수행기관/담당기관/지원기관"`)
  가 거의 모든 row 에서 실패. 추출 성공률 1.5% (1/66, 다른 코트라
  1건은 별건)
- **selector 보강**: `pipeline/jbexport_daily.py:243-258` — th/dt/td.th
  selector 모두 실패 시 plain-text regex fallback (label 변형·콜론·
  공백 흡수, `function(` JS 잡음 + label 자체 재포함 방어)
- **update_db 머지 보호**: `pipeline/update_db.py:221-232, 476-481` —
  `_FALLBACK_ORGS = {'전북수출통합지원시스템', '기업마당'}`. 새 값이
  fallback 이고 옛 값이 진짜 기관명이면 옛 값 보존 (049 동일 패턴:
  ai_summary / attachments_json / recommend_label / notice_chk /
  notice_order 와 같은 머지 정책)
- **위젯 필터 정책 (Phase 6)**: 옵션 A 채택 — `appy.py:891` jbexport
  분기 `organization = '전북수출통합지원시스템'` 필터 제거. 백필 결과
  9개 진짜 기관명 모두 위젯 노출. `source = 'jbexport'` 자체가
  url 도메인 `jbexport.or.kr` 100% 일치라 추가 필터 불필요.
- **백필 스크립트**: `release/2026-05-10_jbexport_org_fix/backfill_organization.py`
- **운영 DB 분포 (백필 후, 67건)**:
  - 46 (재)전북특별자치도 경제통상진흥원
  - 6 코트라 전북지원본부
  - 4 한국무역협회 전북지역본부
  - 3 전주시
  - 3 전북특별자치도
  - 2 전북지방우정청
  - 1 한국무역보험공사 전북지사
  - 1 전주상공회의소
  - 1 (재)전북바이오융합산업진흥원
- **추출 성공률 (050 후)**: 100% (66/66 → 진짜 기관명)
- **commit**:
  - v2 fix `8e9780e` / docs `25097eb`
  - v1 fix `b8df16f` / docs `90d449c`
- **운영(Render) 적용**: 2026-05-10 Render Shell, backup
  `biz.db.backup_20260510_080638_050_org_fix_87b69ccc6d75`
- **검증**: 운영 위젯 1~5위 ↔ `jbexport.or.kr` 사이트 일치 ✅
- **후속 (2026-05-10, 백로그 051)**: 050 적용 후 사용자 시각 검증에서
  공지(notice_chk=1) 2건이 위젯 1~2위 차지하여 연번 66/65 가 밀려나는
  현상 확인. 사용자 정책 = "공지 무시, 연번만 위젯 노출".
  `appy.py:898-909` jbexport 분기에 `AND COALESCE(notice_chk, 0) = 0`
  추가 + ORDER BY 에서 `notice_chk DESC` 제거 (notice_order DESC 만
  유지). v1 로컬 DB 검증: 위젯 1~5위 = notice_order 1544~1540 (사이트
  연번 66~62) 매칭. 049 의 사이트 정렬 충실 재현 정책과 분리된
  "위젯 노출 정책" 결정 — 사이트는 공지 우선, 위젯은 연번만.

### jbtp (2026-05-10, 백로그 053)

- **사이트**: `https://www.jbtp.or.kr/board/list.jbtp?boardId=BBS_0000006`
  (HTML 직접, proxy 무관)
- **카테고리**: A 정렬 키 부재 + C 위젯 필터 누락 (start_date 미추출)
- **선행 상태**: v2 connector 4단계 분리 (백로그 030, 5/9 신설) /
  v1 = legacy 단일파일 (백로그 029 divergence). 위젯 0/5 매칭.
- **확정 정렬 키 (HTML 실측)**:
  - 1차: `notice_chk DESC` (`tr.notice` / `td.notice` CSS class)
  - 2차: `notice_order DESC`
    - 공지: `dataSid` (URL native ID, 페이지 내 표시순)
    - 일반: **td[0] seq** (예: '2198', '2197') — `dataSid` 가 아님
  - 핵심 발견: seq=2198 → dataSid=20137, seq=2196 → dataSid=20152.
    dataSid 비단조 — 사이트 정렬은 td[0] 표시 seq DESC.
- **DB 컬럼**: 049 의 `notice_chk` / `notice_order` 그대로 재사용
  (ALTER 추가 없음). 추출 의미는 source 별로 다름 — 같은 컬럼 재해석.
- **추출 위치**: `connectors/connector_jbtp.py:parse + normalize`
  (4단계 분리 connector 의 `is_notice` / `seq_text` / `reg_date_text`
  raw → normalize 에서 `notice_chk` / `notice_order` / `start_date`
  매핑)
- **위젯 SQL**: `appy.py:load_latest_by_source` jbtp 분기 추가 —
  `WHERE notice_chk = 0` (공지 제외, 051 동일 정책) + ORDER BY
  `notice_order DESC, created_at DESC, id DESC`.
- **start_date (카테고리 C)**: td[6] 등록일 → `start_date`. 백필 전
  33/128 (26%) 만 채워짐 → 위젯 `start_date >= '2026-01-01'` 필터에서
  95건 탈락. 백필 후 122/128 (96%) 채움 (no_match 6 = 9페이지 외).
- **upsert / 머지**: jbtp connector 는 `connectors/_common.save_to_db`
  의 `INSERT OR IGNORE` 만 사용 — `update_db._upsert_one` 경로
  타지 않음. 049 의 generic merge 보호는 비활성. 새 row 부터 정상 채움.
- **검증 5/5** (위젯 시뮬, 공지 제외 top 5 ↔ 사이트 page1 일반글 1~5):
  - 1: seq=2198, dataSid=20137, '2026년 첨단바이오육성 R&D지원사업'
  - 2: seq=2197, dataSid=20129, '2026년 R&D기술사업화 지원사업'
  - 3: seq=2196, dataSid=20152, '인공지능 분야 기술지도'
  - 4: seq=2195, dataSid=20151, '전북AX랩 활용'
  - 5: seq=2194, dataSid=20145, '2026년 2분기 새만금 이차전지'
- **백필**: `release/2026-05-10_jbtp_widget_fix/backfill_jbtp.py`
  (사이트 9페이지 fetch + URL dataSid 매칭 + UPDATE).
  v2 로컬 결과 matched=122, updated=122, no_match=6.
  백업 `biz.db.backup_20260510_205346_053_jbtp_widget_d20796d40565`.
- **사용자 결정 (Phase 6)**:
  - Q1 위젯 공지 정책 = B 공지 제외 (jbexport 051 동일)
  - Q2 v1 sync = X surgical 단순 fix (백로그 029 통째 sync 보류)
- **commit + 운영 적용**: 사용자 push + cherry-pick + Render 백필 대기.

### [다음 source 처리 시 동일 형식으로 항목 추가]

## 5. 다음 source 후보 (적용 우선순위)

### 진단 완료 source

| source | proxy | format | 진단 백로그 | 카테고리 |
|---|---|---|---|---|
| jbexport | 의존 | JSON | 049 / 050 / 051 | A + B + 위젯 정책 |
| jbtp | 무관 | HTML | 053 | A + C |

### 미진단 source

CLAUDE.md 기준 source별 운영 row 수 (2026-05-02 시점 — 진단 시 최신
재확인):

- 🟡 jbbi (~362건) — 사이트 정렬 미진단
- 🟡 jbtp_related (~70건) — JBTP 관련, jbtp 와 동일 패턴 가능성 (미진단)
- 🟡 kseafood / at_global — 별도 사이트, 정렬 미진단
- 🟢 kstartup / bizinfo — 정부 표준 API, 일관성 비교적 높음 (낮은 우선
  순위)

### 사전 점검 체크리스트 (진단 시작 전)

1. **format 식별**: list URL 응답 `Content-Type` 확인 → JSON / HTML 분기
2. **proxy 의존성**: `requests.get` 직접 200 OK 인지 (jbtp 무관) /
   wrapper 필요 (jbexport 의존) 확인
3. **v1/v2 sync 상태**: connector 코드 v1↔v2 divergence 점검
   (`git diff` 또는 파일 비교) — 백로그 029 처럼 통째 divergence
   있으면 fix 경로 (surgical/통째) 사용자 결정 필요
4. **DB row 분포**: source 별 현재 row 수 + start_date / status / null
   분포 → 카테고리 C 위젯 필터 누락 의심 시 미리 진단

선정 기준: 운영 위젯에 노출되며 사용자가 화면 비교 시 "거의 일치 안 함"
이라고 판단할 수 있는 source 부터.

## 6. 참고 자료

- 백로그 049 commit (v2): `02d48f2` (`git show 02d48f2`)
- 백로그 049 발견 경위: `notes/BizGov_새채팅.txt` "추가 발견 (20:40)
  — 백로그 047 신규" 섹션 (백로그 047 → 049 로 ID 이관)
- 5/8 stale 진단 (`notice_create_dt` NULL 발견): `docs/daily/2026-05-08.md`
- 임시 스크립트 명명 규칙: `_check_*.py` (.gitignore 자동 차단)
