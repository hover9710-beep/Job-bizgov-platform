# 백로그 048 — jbexport_daily 가 기존 row 의 status 를 갱신하지 않음

상태: ✅ **완료** (2026-05-10).
발견: 2026-05-10 (백로그 047 진단 중 부수 발견).

## 증상

사이트 jbexport.or.kr list 에서 "접수마감" 으로 표시된 사업이 v1/운영 DB 에 `status='진행'` 로 오래 남아 있음.

확인된 row 4건 (정정 전):

| id | sp_seq[:8] | DB status/raw | 사이트 list status | 사업명 |
|---|---|---|---|---|
| 10061 | 8260a0d4 | 진행/공고중 | **접수마감** | 전주시 AI 활용 디지털 마케팅 |
| 10062 | c02eb9e7 | 진행/접수중 | **접수마감** | 중국 시장 테스트 마케팅 |
| 10063 | 1d902514 | 진행/접수중 | **접수마감** | 서울푸드 연계 JB 바이어 상담회 |
| 10065 | 8d9b66c9 | 진행/접수중 | **접수마감** | JB 해외 바이어 상담회 |

## 원인 (확정)

`update_db._upsert_one` 은 기존 row 에 대해 status UPDATE 를 수행한다.
하지만 `pipeline/jbexport_daily.py:filter_open_announcements` (line 569-578) 가
`OPEN_STATUSES = {"접수중", "공고중"}` 외의 항목을 today.json 에서 제거한다.

흐름:
1. `fetch_all_announcements` → 사이트 list 전체 (마감 포함) `all_items` 수집
2. `filter_open_announcements` → "접수중/공고중" 만 남김 (마감 사업 drop)
3. today.json → merge_jb → update_db: **마감으로 바뀐 사업은 도달조차 안 함**
4. → DB 의 옛 status 그대로 유지

메일/카카오 알림이 "마감" 사업을 안 보내는 정책 자체는 옳음. 하지만 status sync 와 알림 정책이 같은 path 에서 처리되어 묶여있던 것이 원인.

## 임시 정정 (2026-05-10)

- v1 DB: 4 row UPDATE (`scripts/debug/jbexport_b047_followup.py` Step 1)
- 운영 DB: `docs/render_sql/b047_b048_followup.sql` 의 백로그 048 섹션 (Render Shell 적용 필요)

## 코드 fix (적용)

`pipeline/jbexport_daily.py` 에 `sync_status_to_db(all_items)` 함수 추가, `run_daily()` 끝에서 호출.

```python
def sync_status_to_db(all_items: List[Dict[str, Any]]) -> Dict[str, int]:
    """list raw 결과로 DB jbexport row 의 status 를 sync.
    메일/알림 흐름에 영향 없이 status / raw_status 만 갱신."""
```

- url 정확 일치로 매칭, status / raw_status 만 UPDATE (다른 필드 안 건드림)
- 메일/카카오 알림 흐름 (today.json → update_db) 변경 없음
- log: `[status-sync] updated=N skipped=N missing=N`

검증: 단독 호출로 stale row 1건 → 마감 정정 OK, missing url skip OK.

## 영향 범위 — 7 source 점검 결과 (2026-05-10)

| source | 패턴 | DB 진행 / 마감 | risk |
|---|---|---|---|
| jbexport | filter 가 마감 drop | 23 / 45 | ✅ fix 완료 (sync_status_to_db) |
| **kstartup** | URL `bizpbanc-ongoing.do` (진행만 fetch) + status 하드코딩 | **459 / 0** | ✅ fix 완료 (sync_status_to_db, 203 row 정정) |
| jbbi | INSERT OR IGNORE | 0 / 358 | MED — 기존 row update 안 됨 |
| jbtp | INSERT OR IGNORE | 31 / 82 | MED |
| jbtp_related | INSERT OR IGNORE + status 하드코딩 | 0 / 71 | MED |
| at_global | INSERT OR IGNORE | 0 / 192 | MED |
| kseafood | INSERT OR IGNORE | 0 / 236 | MED |
| bizinfo | UPSERT (update_db._upsert_one) | 0 / 2,035 | LOW |

`jbbi/jbtp_related/at_global/kseafood` 가 `진행=0` 인 건 `INSERT OR IGNORE` 로 옛 status 만 남기고, normalize_status 가 다른 라벨로 매핑하기 때문. 사이트 변동 추적 안 됨 — 후속 백로그.

## kstartup fix (2026-05-10 추가)

`connectors/connector_kstartup.py` 에 `sync_status_to_db()` 추가, `--sync-status-only` CLI 모드 + run_all.py 4e 단계.

원리: 사이트 API 가 `bizpbanc-ongoing.do` (진행중만) 만 반환 → connector 도 진행중만 수집 → 사업 마감 시 사이트 list 에서 빠지지만 DB 에는 진행 그대로 남음. 매일 daily 실행 후 update_db 다음에 sync 가 진행 url set 과 DB 진행 row 를 대조해 누락된 row 를 마감으로 마킹.

검증: v1 DB 1회 sync 실행 → 459 진행 → 256 진행 / 203 마감. 사례 row 들의 end_date 가 5/5~5/7 (최근 마감) — 정확.

## 관련 파일

- `pipeline/jbexport_daily.py` (수정 대상)
- `scripts/debug/jbexport_site_vs_db_diff.py` (재현 도구)
- `scripts/debug/jbexport_b047_followup.py` (정정 스크립트)
- `docs/render_sql/b047_b048_followup.sql` (운영 SQL)
