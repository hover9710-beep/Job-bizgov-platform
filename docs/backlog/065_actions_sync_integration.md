# 065. GitHub Actions Daily Crawl 에 /api/sync step 통합 — 5/3 disable 의 진짜 대체

**상태**: 🟢 신규 (W20 사이클)
**발견일**: 2026-05-12 새벽 (사용자 정정 — "PC 스케줄러는 실험용, 진짜 master 는 Actions")
**우선순위**: 高 — 5/3 disable 이후 9일간 진짜 자동화 실효 부재. PC 의존 제거의 사전조건
**연관**: 057 (Phase 2.1~2.3 의 /api/sync 인프라 — 본 백로그가 활용), 058 (v1 connector 정지 진단 — PC 가 실험용이라면 의미 재정의 필요), 061 (전체 파이프라인 명세), 062 (E2E 파이프라인 hook), 064 (4 connector url 정규화 — Actions 가 사이트 fetch 시 동일 검증 필요)

## 한 줄

`.github/workflows/daily-crawl.yml` 끝에 `pipeline/sync_to_render.py` 호출 step 을 추가해 Actions = 진짜 master crawler 로 복귀시키는 작업. 5/3 동적 보호 정책 (DB git push disable) 은 유지하되, 정적 데이터 (`biz_projects`) 만 `/api/sync` 로 push → 운영 DB 자동 갱신. **057 의 진짜 미완 부분** (Phase 2.1f 까지는 PC 호출 구조만 완성).

## 발견 경위 (5/12 새벽 사용자 정정)

5/11~5/12 11시간 057 마라톤 + 5/12 5 connector 정비 종합 종료 직후 사용자 명시:
> "스케줄러는 노크할 때 실험용이었어. 왜 아직도 서버에서 자동화가 안 되고 컴의 스케줄러 작동되는 거야?"

이 정정으로 5/9~5/12 모든 디버깅 흐름 재정렬 — 자세한 컨텍스트는 `docs/daily/2026-05-12.md` 의 **"5/12 새벽 추가 — 크롤링 자동화 부재의 진짜 의미"** 섹션 참조.

### 잘못 알고 있던 구조 (5/11 마라톤 시점)
- PC Windows Task Scheduler (20:37 daily) = master crawler
- GitHub Actions Daily Crawl = success 표시되지만 5/3 disable 로 결과 폐기
- 057 = "stale 해결" 인프라

### 진짜 구조 (5/12 새벽 정정 후)
- PC daily run = 노크/실험용. 사용자 본업 환경에서 가끔 켜는 임시 도구
- GitHub Actions = 진짜 master 가 돼야 했음. 5/3 disable 이 9일간 끊었음
- **057 = 5/3 disable 의 대체 솔루션** (이제야 의미 명확). 그러나 PC 에서 호출하는 구조로 만들어 Actions 와 연결 미완.

## 9일간 실제 상태 (정정)

| 날짜 | GitHub Actions | PC daily run | 운영 DB |
|---|---|---|---|
| 5/4~5/7 | success (결과 폐기) | 사용자 노크 (jbtp 마지막 5/7) | stale |
| 5/8~5/11 | success (폐기) | 안 함 | stale (5/10 backfill 5건 / 5/11 057 마라톤) |
| 5/12 | success (폐기) | 사용자 수동 | jbexport 70 + jbtp 137 정상화 |

→ 9일간 "자동으로 매일 갱신" 사실 **0회**. 057 Phase 2.1e 점심 deploy + 198 row sync 와 5/12 밤/한밤중 처리 모두 사용자 수동 또는 단발 backfill 로만 동작.

## 057 과의 관계 — Phase 2.1f 까지의 미완 부분

057 Phase 2.1a~2.1f 완료 항목:
- `/api/sync` 엔드포인트 ✅
- `pipeline/sync_to_render.py` 호출자 (PC 용) ✅
- `synced_to_render` flag + ALTER ✅
- opt-in wrapper (`auto_run.bat`) ✅
- v1 cherry-pick + 운영 deploy ✅
- 운영 DB ALTER + sync 198건 ✅

본 백로그 (065) 가 처리할 057 미완:
- GitHub Actions 에 `/api/sync` 호출 step 추가 ❌
- Actions 의 fetch 실제 결과 검증 ❌ (success 표시 ≠ 한국 사이트 fetch 성공)
- ADMIN_KEY 를 GitHub Secrets 로 저장 ❌
- PC 의존 제거 ❌

## 진짜 자동화 구조 (목표)

GitHub Actions Daily Crawl (매일 자동, 사용자 PC 무관):
1. 사이트 crawler 실행 (한국 사이트 fetch — bizinfo / jbtp / jbexport / jbbi / at_global / kseafood / jbtp_related)
2. Actions runner 의 임시 DB 에 결과 저장
3. `pipeline/sync_to_render.py` 호출 (`ADMIN_KEY = ${{ secrets.ADMIN_KEY }}`)
4. `/api/sync` 로 정적 데이터 push (`biz_projects` UPSERT)
5. 운영 DB 갱신 (동적 6 테이블 미터치 — 5/3 정책 유지)

→ PC 완전 불필요
→ 5/3 동적 보호 정책 그대로 유지
→ 매일 cron 정해진 시각 자동 실행 (현재 UTC 23:00 = KST 08:00)

## 점검 필요 위험 (Phase 1 진단 항목)

### 1. GitHub Actions 의 한국 사이트 fetch 실제 작동 여부

Actions success 표시가 실제 fetch 성공 의미인지 미확인:
- try/except 로 가려진 실패 가능성
- Actions runner IP = 미국 (Azure). 한국 사이트 (jbtp, jbexport, jbbi 등) 가 미국 IP 차단할 수 있음
- 사용자 메모리에 "Daily Crawl #5~#12 success" 이지만 실제 row 수 미확인 — workflow run log 의 fetch step 출력 검토 필요
- 053 follow-up #2 사고 (Render Shell 의 `jbtp.or.kr` ConnectTimeout) 와 동일 패턴 가능성

확인 방법:
- `.github/workflows/daily-crawl.yml` 전문 review
- 최근 (5/12) Actions run 의 fetch step 실제 출력 (row count / HTTP error)
- 사이트별 차단 여부 (Actions log 의 timeout / 403 / connection refused 검색)
- Actions 의 DB 처리 패턴 (어디에 저장하는지 — runner tmp / git tracked / etc.)

### 2. Actions runner 의 임시 DB

Actions runner 는 매 실행마다 새로 시작 (영속성 없음):
- 옛 패턴 (5/3 이전): git repo 의 `db/biz.db` 사용 → `git add db/biz.db && git push` 로 누적 → Render auto-deploy 가 받아옴
- 새 패턴 (제안): Actions DB 는 매번 임시, `/api/sync` 로 운영 DB 만 갱신
- 또는: Render 운영 DB 를 pull 해서 작업 (보안 위험 — pass)

권장: **매번 임시 DB + `/api/sync` push 만**. 옛 row 와 매칭은 운영 DB 의 `url` UNIQUE 가 처리 (057 Phase 2.1b 의 UPSERT 로직).

→ 즉 Actions DB 의 row 는 단발성. 옛 row 누적은 운영 DB 가 단독 source-of-truth.

### 3. ADMIN_KEY GitHub Secrets

Actions workflow 에서 운영 API 호출 시 `ADMIN_KEY` 필요:
- GitHub Secrets 에 저장 (Settings → Secrets and variables → Actions)
- Actions yaml 에서 `${{ secrets.ADMIN_KEY }}` 로 주입
- 코드 commit 에 노출 0 (PowerShell `$env:ADMIN_KEY` 주입 패턴 — 057 Phase 2.1f 와 동일)

## 진행 방식 (Phase 1/2/3)

### Phase 1 — Actions 진단 (30분)

1. `.github/workflows/daily-crawl.yml` 전문 review (특히 5/3 disable 주석 위치 + 직전 step 들)
2. 가장 최근 (5/12) Actions run 의 fetch step 실제 row 수 확인 (Actions UI 의 log 다운로드)
3. 사이트별 차단 여부 (Actions log 의 HTTP error 검색 — timeout / 403 / "connection refused")
4. Actions 의 DB 처리 패턴 (`run_all.py` 가 어디에 저장 — `db/biz.db` tracked? runner tmp?)

→ Phase 1 결과로 Phase 2 의 진행 가능 여부 결정 (Actions fetch 실패 시 별도 우회 필요)

### Phase 2A — Actions fetch 정상 시: sync step 추가 (1~2시간)

1. yaml 끝에 `sync_to_render.py` 호출 step 추가:
   ```yaml
   - name: Sync to Render
     env:
       ADMIN_KEY: ${{ secrets.ADMIN_KEY }}
     run: python pipeline/sync_to_render.py --dry-run
   ```
2. `ADMIN_KEY = ${{ secrets.ADMIN_KEY }}` GitHub Secrets 설정
3. dry-test (`--dry-run`) 먼저 검증 → workflow_dispatch 수동 trigger 로 1회 실행
4. dry-run log 의 sync 대상 row 수 확인 → 사용자 합의
5. `--dry-run` 제거 후 본 실행 → 운영 위젯 검증

### Phase 2B — Actions fetch 차단 시: 대체 경로 검토

Actions 가 한국 사이트 차단으로 fetch 실패 시 옵션:
- **B1**: Render Cron Job 등록 (한국 IP 차단 동일 — 053 follow-up #2 와 같은 본질). 추가 우회 필요
- **B2**: 한국 IP proxy 서비스 + Actions (외부 의존 추가)
- **B3**: PC daily run + Render sync 패턴 유지 (현재). `auto_run.bat` opt-in 의 자동화 강화 (Task Scheduler 활성화)

Phase 1 결과에 따라 B1/B2/B3 중 선택. 본 백로그는 일단 Phase 2A 우선.

### Phase 3 — PC 의존 제거 (1시간)

Actions 가 매일 정상 갱신 검증 (5/13~5/14 모니터링) 후:
1. PC Windows Task Scheduler 의 BizGov 작업 비활성화 또는 schedule 변경 (수동 trigger 만)
2. `auto_run.bat` 의 sync step (057 Phase 2.1f wrapper) 활성화 결정 (옵션 — 보험으로 유지 가능)
3. 운영 위젯 + Render `MAX(created_at)` 매일 확인 — Actions 만으로 정상 갱신 검증

→ 검증 완료 후 058 백로그 (v1 connector 정지 진단) 의미 재정의 또는 close

## 검증 데이터 (Phase 1 진단 시 사용)

- 5/12 운영 DB 기준점:
  - `jbexport`: 70 row, MAX(notice_order)=68
  - `jbtp`: 137 row, MAX(notice_order)=20248
  - 다른 source: Phase 1 진단에서 확인
- Actions workflow runs: #5 (5/4) ~ #12 (5/11) 모두 success 표시 — 실제 fetch 결과 미확인
- 5/3 disable commit (`.github/workflows/daily-crawl.yml`):
  ```
  # DISABLED 2026-05-03: DB auto-push removed to prevent
  # overwriting dynamic tables (click_log, visit_log,
  # companies, user_request_log, recommendations) on production (Render).
  ```

## 정책 시사점 (백로그 061/062 연관)

| 항목 | 시사 |
|---|---|
| 5/3 결정의 정당성 + 부작용 | 동적 보호는 정당. 그러나 정적 데이터 같이 끊긴 부작용까지 추적 안 됨 → 결정의 영향 범위 명세화 필요 (061 의 동기) |
| 사용자 머릿속 vs 코드 vs AI 인식의 3-way divergence | 사용자 "PC 는 실험용" / 코드 "PC = run_all.py master" / AI "PC 가 master" — 3방향 불일치가 9일간 디버깅 누적의 본질 |
| Actions success 표시 ≠ 실효 | success 가 git push 무효화 + 결과 폐기 일 수 있음. CI status 의 의미를 자동화 실효와 분리 검토 (062 E2E hook 가치 입증) |
| 057 의 진짜 가치 재평가 | 단순 "stale 해결" 아니라 **5/3 disable 의 대체 솔루션**. 본 백로그 (065) 까지 가야 진짜 완료 |

## 메모

- 058 백로그 (v1 connector 정지 진단) 의 의미 재정의 필요 — PC 가 실험용이라면 v1 connector 정지 자체가 무의미. 본 백로그 Phase 3 완료 후 058 close 또는 재명세
- 064 와 동시 진행 가능 — 064 는 connector url 정규화, 065 는 Actions 통합. 다만 Actions 가 kseafood 도 호출하려면 064 Phase 2-B 완료 우선
- ADMIN_KEY GitHub Secrets 저장은 사용자 1회 액션 필요 (Settings UI)
- Phase 2A dry-run 결과는 사용자 합의 후 본 실행 (자동 적용 금지)
- 5/12 새벽 사용자 정정 직후 신설 — fix 는 W20 사이클부터

---

# Phase 1 진단 결과 (2026-05-12 새벽)

## 시나리오 판정: **A 확정** (Actions fetch 정상)

GitHub Actions `Daily BizGov Crawl` workflow run **#13 (5/11 schedule)** 로그 직접 검토:

- 미국 IP (Azure runner) 의 한국 사이트 fetch = **정상 작동**
- `pipeline/jbexport_daily.py` 가 jbexport **70건 수집 + 상세 메타 + 첨부파일 다운로드 성공**
- 5/11 신규 공고 (oder 67, 68) 도 정상 수집 (filter-diag log 에서 신규 url 2건 확인)

→ Phase 2A (sync step 추가) 경로 가능. B1/B2/B3 우회 불필요.

## 발견 1 — DB schema mismatch (Actions runner DB 측)

run #13 종료 시점 traceback:

```
sqlite3.OperationalError: no such column: raw_status
  File "pipeline/jbexport_daily.py", line 1126, in sync_status_to_db
```

원인:
- `pipeline/jbexport_daily.py` 의 `sync_status_to_db()` 가 `raw_status` 컬럼 UPDATE 시도
- Actions runner 의 `db/biz.db` (5/3 시점 정적 사본 또는 매 run 초기화) 에 `raw_status` 컬럼 부재
- 5/3 DB auto-push disable 이후 schema 동기화 메커니즘이 없어 v1 로컬 / 운영 / Actions DB 간 컬럼 divergence
- v1 로컬에서는 어느 시점 ALTER 로 추가됐으나 Actions runner 의 sqlite 파일에는 미반영

영향:
- fetch 까지는 성공해도 sync_status_to_db 단계에서 traceback → 후속 단계 (merge / detect_new / mail / 등) 미실행
- 즉 **Actions 가 매일 jbexport crawl 까진 성공하나 DB write 단계에서 9일간 실패**

## 발견 2 — Actions success 표시 거짓 (CI status 신뢰성)

GitHub UI 의 Status 표시 **"Success"** vs 실제 log 의 **"Process completed with exit code 1"**:

- 사용자 메모리의 "Actions #5~#12 모두 success" → 실제로는 9일간 모두 동일 traceback 으로 실패였을 가능성 (run #13 이 #12 다음 schedule 이므로 동일 패턴 추정)
- workflow yaml 의 `continue-on-error` 또는 step-level error 처리 정책이 step 실패를 masking
- CI status = 자동화 실효 X — 백로그 062 (E2E hook) 의 가치 재입증

→ 사용자 머릿속 ("Actions success = 정상") vs 코드 ("exit 1 but masked") 의 또 한 층 divergence.

## Phase 2 작업 — 사전 fix 다수 필요

본래 계획 (Phase 2A: yaml 끝에 sync_to_render.py step 추가) 만으로는 부족. 다음 사전 fix 필요:

### 사전 fix 1 — `raw_status` 컬럼 처리

| 옵션 | 내용 | 평가 |
|---|---|---|
| **A** | `pipeline/jbexport_daily.py` 의 `sync_status_to_db()` 가 컬럼 부재 시 `ALTER TABLE` 또는 skip (defensive) | 본 함수 한 곳만 수정. Actions / v1 / 운영 환경 차이 흡수. 우선 |
| B | `scripts/migrate_*.py` 에 `raw_status` 마이그레이션 추가 + Actions yaml 의 init step 에서 호출 | 정공법이나 마이그레이션 인프라 일관성 필요 (별도 백로그?) |
| C | 코드 측에서 `raw_status` 사용 제거 (다른 컬럼으로 대체) | 의미 손실 가능 — 사용처 전수조사 선행 |

→ W20 사이클에서 결정. A 우세 추정 (영향 최소화).

### 사전 fix 2 — Actions success/failure 표시 정합성

`.github/workflows/daily-crawl.yml` 의 step error 처리 점검:
- `continue-on-error: true` 사용처 식별 → 의도된 곳 (외부 의존 step) 만 남기고 핵심 step 은 `false`
- 또는 step `if: failure()` 활용으로 traceback step 후 명시적 exit
- 검증: workflow_dispatch 수동 trigger 로 의도적 실패 1회 → UI 가 failure 로 표시되는지

### 사전 fix 3 — /api/sync step 추가 (본 백로그 본질)

위 사전 fix 1~2 완료 후:
- yaml 끝에 `pipeline/sync_to_render.py --dry-run` step 추가 (`ADMIN_KEY = ${{ secrets.ADMIN_KEY }}`)
- dry-run 결과 합의 → `--dry-run` 제거 → 본 실행

## 진단으로 갱신된 위험 평가

| 항목 | Phase 1 진단 전 | Phase 1 진단 후 |
|---|---|---|
| Actions fetch 한국 사이트 차단 | ❓ 불명 (시나리오 B 우려) | ✅ 정상 (시나리오 A 확정) |
| Actions DB schema 일관성 | ❓ 미점검 | ❌ raw_status 부재 — 사전 fix 1 필요 |
| Actions CI status 신뢰성 | ❓ 미점검 | ❌ exit 1 이 success 로 마스킹 — 사전 fix 2 필요 |
| sync step 추가 단순도 | "yaml 1 step 추가" | **3-fix sequence** (raw_status → status 정합성 → sync step) |

## 5/12 새벽 종료

진단만 완료. Phase 2 fix 는 W20 fresh 사이클. 본 진단 결과로 065 의 Phase 2A 범위가 "yaml 1 step 추가" 에서 "3-fix sequence (raw_status → status 정합성 → sync step)" 로 확대 — W20 추정 시간도 1~2시간 → 3~4시간으로 재산정.

5/12 일자 작업 (점심 057 Phase 2.1e + 저녁 jbexport fix + 밤 jbtp fix + 한밤중 029/064 + 새벽 자동화 부재 진단 + Actions Phase 1 진단) **종합 종료**.
