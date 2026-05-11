# release/2026-05-11_b057_phase21f_wrapper — 백로그 057 Phase 2.1f

## 목적

v1 daily wrapper (`auto_run.bat`) 에 **opt-in 형태의 Render sync step** 추가.
실제 활성화는 Phase 2.1e (Render `/api/sync` deploy) 완료 후 사용자가 환경변수 set 하여 결정.

자세한 배경: `docs/backlog/057_jbtp_sync_diagnosis.md` Phase 2.1f.

## 의존성 (선행 조건)

| 의존 | 상태 | 위치 |
|---|---|---|
| Phase 2.1a — biz_projects 컬럼 추가 (v1 로컬 DB) | ⚠ 적용 필요 | `scripts/migrate_add_sync_columns.py` (v1 commit db0f8cc) |
| Phase 2.1b — Render `/api/sync` 엔드포인트 | ⚠ deploy 필요 | `release/2026-05-11_b057_phase21b_sync/` |
| Phase 2.1c — `pipeline/sync_to_render.py` | ⚠ v1 cherry-pick 필요 | 본 release 폴더 또는 v2 commit e71d455 |
| Phase 2.1e — 운영 DB 컬럼 추가 + appy.py deploy | ⚠ 별도 작업 | Render Shell + 자동 deploy |

**활성화 (ENABLE_RENDER_SYNC=1) 는 위 4개 모두 완료 후에만**. 미충족 상태에서 활성화 시 매일 sync fail (404 또는 컬럼 없음 에러) — fail 자체는 alert 안 보내고 log 만 (idempotent retry).

## 파일 변경

| 파일 | 변경 | 적용 위치 |
|---|---|---|
| `auto_run.bat` | step 5 (sync) 신규 추가, opt-in (`if defined ENABLE_RENDER_SYNC`) | v1 루트 |
| `pipeline/sync_to_render.py` | 신규 파일 (v2 commit e71d455 의 v1 cherry-pick) | v1 `pipeline/` |

## auto_run.bat 변경 요약

```
1) proxy check                            [기존]
2) proxy auto-start (if dead)             [기존]
3) run_all.py                             [기존]
4) proxy cleanup                          [기존]
5) sync_to_render (Render UPSERT)         [신규 — opt-in]
6) alert (if run_all failed)              [기존, 번호만 5→6]
```

`5) sync_to_render` 동작 (활성화 시):

| 조건 | 동작 |
|---|---|
| `ENABLE_RENDER_SYNC` env var 정의되지 않음 (기본) | step 자체 skip (silent) |
| `ENABLE_RENDER_SYNC` 정의 + run_all 성공 (exit=0) | `py pipeline\sync_to_render.py` 실행 → log 기록 |
| `ENABLE_RENDER_SYNC` 정의 + run_all 실패 (exit≠0) | sync skip + skip 사유 log 기록 |
| sync_to_render 자체 실패 (network/HTTP 에러) | log 기록만, alert 미발송 (멱등성 — 내일 재시도, Phase 2.5 W20+ 에서 정식 알림) |

`SYNC_EXIT` 값은 alert 트리거 조건에서 제외 — 이는 정책상 의도된 결정 (sync 실패는 운영 영향 0).

## 활성화 절차 (사용자 결정 후)

### 0. 선행 조건 확인

```cmd
REM 0-1) v1 로컬 DB 에 컬럼 있는지
sqlite3 db\biz.db "PRAGMA table_info(biz_projects);" | findstr synced
REM 출력에 synced_to_render / synced_at 두 줄 보여야 함.
REM 없으면: py scripts\migrate_add_sync_columns.py

REM 0-2) pipeline\sync_to_render.py 존재 확인
dir pipeline\sync_to_render.py

REM 0-3) Render 측 /api/sync 응답 확인
curl -X POST https://job-bizgov-platform.onrender.com/api/sync ^
  -H "Content-Type: application/json" ^
  -d "{\"key\":\"<ADMIN_KEY>\",\"source\":\"test\",\"rows\":[]}"
REM 기대 응답: {"ok":true,"count":0,...}
REM 403 면 ADMIN_KEY 오류, 404 면 deploy 미완료.
```

### 1. dry-run 검증 (v1)

```cmd
py pipeline\sync_to_render.py --dry-run
REM 출력: pending 총 N건, source 별 분포. POST/DB UPDATE 없음.
```

### 2. 소량 source 1회 실시간 테스트 (예: jbtp 128건)

```cmd
py pipeline\sync_to_render.py --source jbtp
REM 출력: inserted/updated/marked_synced
REM Render Shell 에서: SELECT COUNT(*) FROM biz_projects WHERE source='jbtp';
REM 운영 DB 가 v1 와 같은 수 도달했는지 확인.
```

### 3. 시스템 환경변수 set

```cmd
REM 명령 프롬프트 (관리자 권한)
setx ENABLE_RENDER_SYNC 1 /M
REM /M = 시스템 전역. 작업 스케줄러도 이 env var 상속.
REM 또는 GUI: 시스템 속성 → 환경 변수 → 시스템 변수 → 새로 만들기
```

### 4. 다음 20:37 Win Task 자동 실행 확인

`logs/auto_run.log` 끝부분:
```
[auto_run] YYYY-MM-DD HH:MM:SS sync_to_render start
...
[sync_to_render] === 결과 ===
  inserted: ...
  updated: ...
  ...
[auto_run] YYYY-MM-DD HH:MM:SS sync_to_render exit=0
```

### 5. 1주 모니터링 체크리스트

| 항목 | 확인 |
|---|---|
| 매일 20:37 Win Task 실행 | `logs/auto_run.log` 일자 확인 |
| sync_to_render exit=0 | log 의 `sync_to_render exit=` 값 |
| Render 운영 DB 누적 | Render Shell `SELECT source, COUNT(*), MAX(created_at) FROM biz_projects GROUP BY source;` |
| pending row 0 도달 | v1 `SELECT COUNT(*) FROM biz_projects WHERE synced_to_render=0;` 일자별 추이 |
| 운영 enrich 보존 | Render `SELECT COUNT(*) FROM biz_projects WHERE ai_summary IS NOT NULL;` 일자별 추이 (감소 없어야) |

## 첫 sync 예상치 (Phase 2.2 + 2.3)

첫 활성화 직후 1회 실행 시 (v1 master 의 모든 row 가 synced_to_render=0 상태):

| source | v1 row | 운영 추정 | INSERT | UPDATE |
|---|---|---|---|---|
| bizinfo | 10,684 | ? | ~1,688 | ~9,000 |
| kstartup | 400 | ? | ~60 | ~340 |
| jbbi | 369 | ? | ~7 | ~362 |
| jbtp | 128 | 113 | ~15 | ~113 |
| jbexport | 65 | ? | ~4 | ~61 |
| jbtp_related | 71 | ? | ~1 | ~70 |
| at_global | 203 | ? | ~3 | ~200 |
| kseafood | 244 | ? | ? | ? |
| **총합** | **~12,164** | | **~1,800** | **~10,400** |

총 약 12,000 row 처리. batch_size=500 기본 → 약 24 batch. 첫 sync 단일 실행 약 5~15분 예상 (Render cold start + 처리). 그 후 매일 incremental delta (보통 수십 건).

## 비활성화 (롤백)

```cmd
REM ENABLE_RENDER_SYNC 제거
setx ENABLE_RENDER_SYNC "" /M
REM 또는 GUI 에서 env var 삭제. 다음 Task 부터 step 자체 skip.
REM auto_run.bat 자체 롤백은 git checkout 또는 backup 사용:
copy auto_run_backup_2026-04-05.bat auto_run.bat
REM 또는 본 release 의 auto_run.bat.original 사용.
```

## 영향 범위

| 영역 | 영향 |
|---|---|
| 기존 daily run (proxy / run_all / cleanup / alert) | 0 — 새 step 은 분기 안에 격리 |
| 미활성 (`ENABLE_RENDER_SYNC` 미정의) 상태 | 0 — 분기 자체 skip |
| 활성 + run_all 실패 | 0 — sync skip + log |
| 활성 + sync 자체 실패 | 0 — log only (alert 안 발송) |
| 활성 + sync 성공 | 운영 DB UPSERT (biz_projects only, 동적 테이블 미터치) |
| 사용자 PC | wrapper 1 step 추가 외 변경 0 |

## 핵심 정책 적용 (백로그 057 Phase 2)

| # | 정책 | 본 release 의 보장 |
|---|---|---|
| 1 | Incremental sync | sync_to_render 가 `synced_to_render=0` 만 query |
| 2 | url unique UPSERT | server-side /api/sync 가 url 매칭 |
| 3 | 연번 ≠ sync 기준 | flag 만 사용, notice_order 무관 |
| 4 | synced_to_render flag = 단일 추적 | 성공 응답 시 flag=1, synced_at=CURRENT_TIMESTAMP |
| 5 | Empty payload skip | sync_to_render 가 pending 0 시 POST skip + 로그만 |
| 6 | 동적 테이블 미터치 | server-side enforcement (whitelist 24 컬럼) |

## 후속 (W20+)

- Phase 2.4 — UPDATE merge 보호 컬럼 화이트리스트 정밀화 (049 패턴 확장)
- Phase 2.5 — sync 실패 알림 정식 (현재는 log only) — kakao / mail
- Phase 2.6 — 동기화 통계 대시보드 (synced_at, source 별 pending row 수, 1주 추세)

## 백로그 참조

- 057: master 명세
- 036: auto_run.bat 의 birth (proxy auto-start wrapper)
- 042: silent fail prevention (alert step)
- 052: jbexport proxy/sync — Phase 2 완료 시 통합 close

## 파일 목록

- `MANIFEST.md` (본 파일)
- `auto_run.bat` (수정본, v1 deploy 사본)
- `auto_run.bat.original` (수정 전 v1 사본, 롤백 참조)
- `DIFF.patch` (unified diff)
- `pipeline/sync_to_render.py` (v1 cherry-pick 사본, 2.1c 결과물 동일)

## 커밋

- v2 commit: (생성 후 추가)
- v1 commit: 별도 deploy 결정 후 (2.1e 와 함께 또는 별도)
