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

해당 source 의 list API 호출 → 첫 5건의 raw JSON 출력. proxy 가 필요한
사이트(jbexport 같은)는 `auto_run.bat` wrapper 또는 수동 proxy 기동 후
호출.

표준 패턴(파이썬, 임시 스크립트):

```python
# _check_<source>_raw.py  (.gitignore 차단 패턴, 사용 후 삭제)
import json, requests
r = requests.get("<LIST_ENDPOINT>", params={"start": 0, "length": 5}, timeout=30)
data = r.json()
items = data.get("data") or data.get("list") or data
print(json.dumps(items[:5], ensure_ascii=False, indent=2))
```

출력 5건의 모든 필드를 한 번 훑는다. 다음 단계(후보 식별)의 입력.

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

### [다음 source 처리 시 동일 형식으로 항목 추가]

## 5. 다음 source 후보 (적용 우선순위)

CLAUDE.md 기준 source별 운영 row 수 (2026-05-02 시점 — 진단 시 최신
재확인):

- 🟡 jbtp (~183건) — JBTP 자체 사이트, 정렬 미진단
- 🟡 jbbi (~362건) — 사이트 정렬 미진단
- 🟡 jbtp_related (~70건) — JBTP 관련 사이트, 정렬 미진단
- 🟡 kseafood / at_global — 별도 사이트, 정렬 미진단
- 🟢 kstartup / bizinfo — 정부 표준 API, 일관성 비교적 높음 (낮은 우선
  순위)

선정 기준: 운영 위젯에 노출되며 사용자가 화면 비교 시 "거의 일치 안 함"
이라고 판단할 수 있는 source 부터.

## 6. 참고 자료

- 백로그 049 commit (v2): `02d48f2` (`git show 02d48f2`)
- 백로그 049 발견 경위: `notes/BizGov_새채팅.txt` "추가 발견 (20:40)
  — 백로그 047 신규" 섹션 (백로그 047 → 049 로 ID 이관)
- 5/8 stale 진단 (`notice_create_dt` NULL 발견): `docs/daily/2026-05-08.md`
- 임시 스크립트 명명 규칙: `_check_*.py` (.gitignore 자동 차단)
