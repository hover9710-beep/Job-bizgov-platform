# 2026-05-13 — 백로그 065 Phase 2-A 진단 보고

## 목적

W20 fresh 사이클의 Phase 2-B (실제 fix) 진입 시 입력 자료.
**진단 only — 코드 / yaml / DB / Secrets 변경 0.**

## 파일

| 파일 | 내용 |
|---|---|
| 이 MANIFEST.md | 진단 결과 요약 + Phase 2-B 작업 단위 |
| `../../../docs/daily/2026-05-13.md` | 전체 진단 상세 (저녁 자동화 검증 1차 + 백로그 065 Phase 2-A 4항목) |
| `../../../docs/backlog/065_actions_sync_integration.md` | 백로그 본문 (Phase 1 결과 + Phase 2 범위) |

## 진단 결과 4건 — 요약

### #1 raw_status 사용 범위
- READ: appy.py 13곳, pipeline/jbexport_daily.py:1102, pipeline/flask_ui_audit.py:73
- WRITE: connector_at_global, connector_kseafood (2 connector)
- UPDATE 호출 (실패 지점): pipeline/jbexport_daily.py 의 `sync_status_to_db`
- **방어책 (이미 존재)**: appy.py:329 `_safe_add(...)` — 서버 boot 시점에만 발동, Actions crawler path 에서는 미발동

### #2 옵션 A 의 구체 위치
- raw_status touch distinct connector = 3 (at_global, kseafood, jbexport)
- 사용자 rule (2~3 → b) → **권고: b** (`pipeline/_ensure_schema.py` 신설 + connector import)
- **추가 발견**: appy.py `_safe_add` 리스트가 outdated — `synced_to_render`, `synced_at`, `notice_chk`, `notice_order`, `notice_create_dt` 5건 누락
- **보충 권고**: c-light (yaml init step 에서도 `_ensure_schema.py` 호출) — 방어 깊이

### #3 daily-crawl.yml 진단 8건
1. `continue-on-error: true` 전수 → Actions UI "Success" 거짓 근거
2. "Ensure DB file exists" step 부재 (5/5 commit `6ffbd1c` 에 있었던 step 사라짐)
3. schema ensure step 부재
4. `/api/sync` POST step 0개
5. DISABLED 코멘트 (5/3) — historical context
6. JBEXPORT proxy nohup 패턴
7. 순서: bizinfo 첫, jbexport 마지막
8. timeout 합계 = 정확 60분 (여유 0)

### #4 sync_to_render.py 인터페이스
- env: **ADMIN_KEY** + RENDER_URL + DB_PATH
- /api/sync: POST body `{key, source, rows}`, **body-auth**
- exit code: fatal-only 1, batch-level 실패는 0 → yaml aggregation 시 stdout 파싱 필요
- schema dependency: `synced_to_render` + `synced_at` 필수 (없으면 exit 1)
- payload whitelist 25 컬럼 (운영 enrich 미전송)
- Secrets: **ADMIN_KEY 1개만** 필요

## Phase 2-B 작업 단위 (5건, W20 진입 후)

1. `pipeline/_ensure_schema.py` 신설 — 28+ 컬럼 통합 ALTER, idempotent
2. connector 측 import + 호출 (at_global / kseafood / jbexport_daily / update_db)
3. appy.py:319-346 consolidation (선택, 별 사이클 가능)
4. yaml 변경:
   - install deps 다음 schema ensure step (c-light)
   - jbexport step 다음 `/api/sync` step
   - 마지막 aggregation step (exit code 1 if batches_fail > 0)
   - timeout 60 → 75분
   - `continue-on-error` 정책 재검토
5. Secrets 추가 (사용자 작업) — ADMIN_KEY 1개

## 추정 시간

**3~4시간** (어제 추정 2시간의 ~2배 — schema fragmentation + aggregation 설계 확대)

## 🟨 사용자 결정 사항 4건 (Phase 2-B 진입 전 사전 조건)

| # | 항목 | 권고 / 사실 |
|---:|---|---|
| (1) | 옵션 A 최종 확정 | 사실상 확정 (B/C 비교에서 A 명백 우세) |
| (2) | 후보 a/b/c 결정 | **b (메인) + c-light (yaml 보충)** 권고 |
| (3) | Secrets 추가 시점 + 목록 | **ADMIN_KEY 1개**, Phase 2-B 적용 직전 |
| (4) | Phase 2-B 진행 시점 | **W20 fresh 사이클** — 지금은 아님 |

## 5/13 자동화 검증 1차 결과 (부수)

- PC daily run 20:37:58 fire → wrapper exit=0 (5분 1초)
- 4 aux connector 자동 호출 ✅: jbtp/jbbi/at_global/jbtp_related 전부 exit 0
- DB 변동: jbtp +2, jbexport +1, bizinfo +1246, 외 0
- **at_global 205/0/205** = URL 정규화 idempotent 결정적 증거 (백로그 064 fix 실효성)
- 사고 #2/#5 재발 0건
- 🚨 5/13 신규 1,250 row 전부 `synced_to_render=0` (auto_run.bat sync step 누락 영향)
- 운영 위젯 jbtp top notice_order=20248 (5/12 그대로) — 시각적 sync 미발동 증거

## 5/13 사이클 분리 메타

| 지표 | 5/12 마라톤 | **5/13** |
|---|---:|---:|
| 사고 발생 | 5건 | **0건** |
| inline fix | (사이클 내) | **0건** |
| code commit | 5+ | **0건** |
| 새 백로그 신설 | 5건 | **0건** |

→ `feedback_cycle_separation.md` 정책 완전 준수.
