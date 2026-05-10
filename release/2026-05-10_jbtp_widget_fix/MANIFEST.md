# release/2026-05-10_jbtp_widget_fix — 백로그 053

## 목적
jbtp 위젯이 사이트와 0/5 매칭. 진단 결과 두 가지 원인:
1. **start_date 미추출 95/128 (74%)** → 위젯 SQL `start_date >= '2026-01-01'` 필터에서 탈락
2. **정렬 키 부재** → 사이트 표시순 (notice_chk DESC, seq DESC) 미반영

→ 추출 보강 + 위젯 SQL 적용 + 기존 row 122/128 백필.

## 사용자 결정 (2026-05-10)
- **Q1 위젯 공지 정책**: B 공지 제외 (jbexport 051 동일 정책, 사용자 일관성)
- **Q2 v1 sync 범위**: X surgical 단순 fix (백로그 029 connector divergence 는 별도 잔존)

## 코드 변경 (v2)

| 파일 | 변경 |
|---|---|
| `connectors/connector_jbtp.py` | `parse()` 에 `is_notice` / `reg_date_text` / `seq_text` 추출 추가. `normalize()` 에 `start_date` (td[6]) / `notice_chk` / `notice_order` 채움. `notice_order` = 공지 시 dataSid, 일반 시 seq (사이트 표시순 일치). `COLS` 에 두 컬럼 추가. |
| `appy.py` | `load_latest_by_source` jbtp 분기 추가: WHERE `notice_chk=0` + ORDER BY `notice_order DESC, created_at DESC, id DESC` (jbexport 049/051 패턴 동일). |

스키마/머지 보호: 백로그 049 잔재 그대로 사용 (`_init_db` 의 `notice_chk`/`notice_order` ALTER + `_upsert_one` 의 generic merge 보호).

## 핵심 발견 (playbook 패치)
사이트 정렬 키 = **dataSid 가 아닌 td[0] seq**. seq=2198 → dataSid=20137, seq=2196 → dataSid=20152 — dataSid 비단조. 공지는 td[0]='[공지]' 라 seq 없음 → dataSid 사용. connector 분기 처리.

## 백필 결과 (v2 local DB)

### DRY_RUN 검증
```
matched: 122  updated: 122  unchanged: 0  no_match: 6
```
no_match 6 = 사이트 9 페이지 외 옛 row (정상).

### 분포 변화

| 지표 | BEFORE | AFTER |
|---|---|---|
| total | 128 | 128 |
| notice_chk=1 | 0 | 32 |
| start_date 채워짐 | 33 | 122 |
| start_date >= 2026-01-01 | 33 | 122 |

### 위젯 시뮬 (공지 제외 top 5) — 사이트 page1 일반글 1~5위 정확 매칭

| 순위 | seq | dataSid | 등록일 | 제목 |
|---|---|---|---|---|
| 1 | 2198 | 20137 | 2026-05-06 | 2026년 첨단바이오육성 R&D지원사업 모집공고 |
| 2 | 2197 | 20129 | 2026-05-04 | 2026년 R&D기술사업화 지원사업 지원계획(2차) 공고 |
| 3 | 2196 | 20152 | 2026-05-07 | 인공지능 분야 기술지도 희망기업 모집 상시공고 |
| 4 | 2195 | 20151 | 2026-05-07 | 전북AX랩 활용 희망기업 모집 상시공고 |
| 5 | 2194 | 20145 | 2026-05-06 | 2026년 2분기 새만금 이차전지 특화단지 기업 애로사항 조사 공고 |

### 백업 (v2 local)
`biz.db.backup_20260510_205346_053_jbtp_widget_d20796d40565`

## 운영 적용 절차 (Phase 8 — 사용자 승인 후)

### 1) v2 push
```
git push origin main
```

### 2) v1 surgical sync (옵션 X)
v1 의 `connectors/connector_jbtp.py` (legacy 단일파일) 와 `appy.py` 에 동일 patch 적용. v2 commit 을 cherry-pick 하거나 수동 patch.

### 3) Render Shell 백필 (운영 DB)
```bash
# DRY_RUN 먼저 (영향 없음)
DRY_RUN=1 python release/2026-05-10_jbtp_widget_fix/backfill_jbtp.py

# apply
python release/2026-05-10_jbtp_widget_fix/backfill_jbtp.py
```

### 4) 위젯 시각 검증
운영 위젯 jbtp 5건 ↔ jbtp.or.kr page 1 일반글 1~5위 비교.

## 산출
- `backfill_jbtp.py` — 사이트 9페이지 fetch + dataSid 매칭 + UPDATE + DRY_RUN ROLLBACK 시뮬
- `MANIFEST.md` (이 파일)

## 참고
- 백로그: `docs/backlog/053_jbtp_widget_fix.md`
- Render SQL: `docs/render_sql/b053_followup.sql`
- Playbook 패치: `docs/playbook/site_sort_audit.md` §3, §4, §5
