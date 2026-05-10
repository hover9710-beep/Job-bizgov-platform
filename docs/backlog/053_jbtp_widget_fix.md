# 백로그 053 — jbtp 위젯 정렬/start_date 추출 fix

**상태**: v2 코드 + 로컬 DB 백필 완료. v1 sync + Render 운영 적용 사용자 승인 대기.
**발견**: 2026-05-10 (jbexport 049/050/051 후속 진단 — playbook §3 적용 시)
**연관**: 029 (v1/v2 connector divergence — 본 백로그에서 surgical 만, 통째 sync 보류)

## 한 줄
jbtp 위젯이 사이트와 0/5 매칭. 원인 = start_date 미추출 (95/128) + 정렬 키 부재. 추출 보강 + WHERE/ORDER BY 적용 + 122 row 백필 → 사이트 page1 일반글 1~5위 정확 매칭.

## 진단 (직전 task)

| 핵심 | 내용 |
|---|---|
| #1 | start_date 추출 95/128 (74%) 미반영 → 위젯 SQL `start_date >= '2026-01-01'` 필터에서 탈락 |
| #2 | 정렬 키 부재 → 사이트 표시순 (notice_chk DESC, seq DESC) 미반영 |
| 사이트 fetch | proxy 무관 (jbexport 와 다름, requests.get() 200 OK) |
| 형식 | HTML (jbexport 의 JSON list API 와 다름) |
| connector 상태 | v2 = 4단계 분리 (5/9 신설, 백로그 030), v1 = legacy 단일파일 (백로그 029 divergence) |

### HTML 구조 (jbtp.or.kr/board/list.jbtp BBS_0000006)

8 td:
- `td[0]` — `class='notice'` 면 `[공지]`, 아니면 seq 번호 (예: '2198')
- `td[1]` — `txt_left a` (제목 + dataSid href)
- `td[2]` — `t_date` 마감일 (예: '2026-05-20 18:00')
- `td[3]` — `t_dday` 상태 (`접수중`/`마감`, 공지는 빈값)
- `td[4]` — 빈
- `td[5]` — 작성자
- `td[6]` — 등록일 (예: '2026-05-06') ← `start_date` 매핑
- `td[7]` — 조회수

### 핵심 발견: 정렬 키
- **사이트 표시순 = seq DESC** (td[0] 텍스트), dataSid DESC 가 아님
- 예: seq=2198 → dataSid=20137, seq=2196 → dataSid=20152 (dataSid 비단조)
- 공지는 td[0]='[공지]' 라 seq 없음 → dataSid 사용 (페이지 내 표시순)
- 통합: `notice_chk DESC, notice_order DESC` (notice_order = 공지면 dataSid, 일반이면 seq)

## 사용자 결정 (Phase 6)

| Q | 결정 | 근거 |
|---|---|---|
| Q1 위젯 공지 정책 | **B 공지 제외** | jbexport 051 동일 정책 — 사용자 일관성. 공지 32/122 (26%) → 포함 시 위젯 5/5 모두 공지 (일반글 안 보임) |
| Q2 v1 sync 범위 | **X surgical 단순 fix** | 빠름. 백로그 029 (connector 통째 divergence) 는 별도 잔존 |

## 적용

### v2 코드 변경

| 파일 | 변경 |
|---|---|
| `connectors/connector_jbtp.py` | `parse()` 에 `is_notice` / `reg_date_text` / `seq_text` 추출 추가. `normalize()` 에 `start_date` (td[6]) / `notice_chk` / `notice_order` 채움. `notice_order` = 공지 시 dataSid, 일반 시 seq. `COLS` 두 컬럼 추가. |
| `appy.py` | `load_latest_by_source` jbtp 분기: WHERE `notice_chk=0` + ORDER BY `notice_order DESC, created_at DESC, id DESC` (049/051 패턴) |

스키마/머지 보호: 백로그 049 잔재 그대로 (`_init_db` ALTER + `_upsert_one` generic merge).

### 백필 (v2 로컬)
- `release/2026-05-10_jbtp_widget_fix/backfill_jbtp.py`
- DRY_RUN PASS → apply: matched=122, updated=122, no_match=6 (9페이지 외 옛 row)
- 백업: `biz.db.backup_20260510_205346_053_jbtp_widget_d20796d40565`

### 분포 변화 (v2 로컬)

| 지표 | BEFORE | AFTER |
|---|---|---|
| total | 128 | 128 |
| notice_chk=1 | 0 | 32 |
| start_date 채워짐 | 33 | 122 |
| start_date >= 2026-01-01 | 33 | 122 |

### 위젯 시뮬 — 공지 제외 top 5 (사이트 page1 일반글 1~5위 정확 매칭)

| 순위 | seq | dataSid | 등록일 | 제목 |
|---|---|---|---|---|
| 1 | 2198 | 20137 | 2026-05-06 | 2026년 첨단바이오육성 R&D지원사업 모집공고 |
| 2 | 2197 | 20129 | 2026-05-04 | 2026년 R&D기술사업화 지원사업 지원계획(2차) 공고 |
| 3 | 2196 | 20152 | 2026-05-07 | 인공지능 분야 기술지도 희망기업 모집 상시공고 |
| 4 | 2195 | 20151 | 2026-05-07 | 전북AX랩 활용 희망기업 모집 상시공고 |
| 5 | 2194 | 20145 | 2026-05-06 | 2026년 2분기 새만금 이차전지 특화단지 기업 애로사항 조사 공고 |

## 운영 적용 (Phase 8 — 사용자 승인 후)

```bash
# 1) v2 push (사용자)
git push origin main

# 2) v1 surgical sync — 사용자가 cherry-pick 또는 수동 patch (옵션 X)
#    대상: v1/connectors/connector_jbtp.py (legacy 단일파일), v1/appy.py

# 3) Render Shell 백필
DRY_RUN=1 python release/2026-05-10_jbtp_widget_fix/backfill_jbtp.py
python release/2026-05-10_jbtp_widget_fix/backfill_jbtp.py

# 4) 위젯 시각 검증 (jbtp.or.kr page1 일반글 1~5 ↔ 운영 위젯)
```

## 교훈 / playbook 패치

1. **HTML 사이트의 정렬 키 ≠ 내부 ID**. dataSid 단조 가정 X. td[0] seq 같은 표시 키 검증 필수
2. **위젯 필터 (start_date / status)** 가 추출 누락 시 silent drop. 진단 카테고리 C 신규
3. **HTML vs JSON list 분기** — 진단 명령이 다름 (BeautifulSoup tr.notice / dataSid vs json.dumps)
4. **사전 점검에 v1/v2 sync 상태**: 029 divergence → fix 경로 (surgical/통째) 결정 필요
5. **공지 정책 일관성**: 사이트 마다 공지 비율 다름 (jbtp 26%, jbexport ~30%) → 위젯 정책 통일 (제외) 가 사용자 정책

→ `docs/playbook/site_sort_audit.md` §3, §4 jbtp 사례, §5 표 추가.
