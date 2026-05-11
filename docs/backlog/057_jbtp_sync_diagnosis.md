# 057. jbtp 운영 DB 5/2~5/7 신규 누적 안된 원인 진단

**상태**: 🟢 신규 (다음 주 진단)
**제안일**: 2026-05-10
**발견**: 5/10 백로그 053 follow-up #2 — Render IP 차단 우회 sync 실행 시뮬에서 운영 113 ↔ v2 128 (15건 차이) 발견
**우선순위**: 높음 — 052 와 동일 chain 사고 가능성, 운영 데이터 stale 위험
**연관**: 052 (jbexport proxy/sync 자동화), 029 (v1/v2 connector divergence)

## 알려진 사실

### v2 vs 운영 차이
- **v2 로컬 DB jbtp**: 128 row (053 백필 ground-truth, 사이트 9페이지 동기)
- **운영 DB jbtp** (Render): 113 row (053 sync 실행 전 시점)
- **차이**: 15 row = 5/4~5/7 사이트 신규 등록 분 (시뮬 검증)
  - notice_order DESC 상위 15 url 이 운영 DB 미존재
  - 시뮬: v1 DB 사본에서 최신 15 url 삭제 → 113 row stale 재현 → sync_jbtp_v1_to_render.py UPSERT → 128 row 복구 PASS

### v1 로컬 vs 운영 차이
- v1 로컬 DB jbtp = 128 row (5/10 053 백필 후 v2 와 동일 상태로 가정 — sync 직전 시뮬 데이터)
- 즉 **v1 로컬에는 신규 row 가 들어왔지만, 운영에는 누적되지 않음** (5/2~5/7 6일간)

## 가설

### H1 — jbtp 운영 sync 메커니즘 자체가 미작동
- 운영 DB 가 v1 로컬 DB 의 변경분을 자동으로 받아오는 메커니즘이 없을 가능성
- 백로그 052 와 동일 패턴 (jbexport 도 같은 chain) → **공통 sync 자동화 부재**

### H2 — Render daily run 이 jbtp 만 실패
- 운영 측 daily 가 jbtp 사이트 fetch 시 IP 차단 (053 follow-up #2 에서 확인) → 매 daily 실패
- 다른 source (bizinfo / kstartup / 등) 는 정상 누적되는데 jbtp 만 stale 인지 확인 필요

### H3 — proxy down (5/8~) 와는 시기 불일치
- jbexport 052 는 proxy 5/8~ down 이 원인. 그러나 jbtp 는 5/2~5/7 (proxy down 이전) 부터 stale.
- jbtp 는 proxy 무관 (HTML 직접 호출, 053 진단에서 확인) → proxy 문제 아닌 다른 원인

## 확인 필요 사항

### 1) 운영 DB sync 메커니즘 식별
- Render Cron Job 등록 현황 (jbtp 별도 cron 이 있는지)
- v1 로컬 daily run 이 운영 DB 에 push 하는 경로 (있는지 / 없는지)
- 자동 commit / 자동 deploy hook 흐름 추적
- 결과: **sync 메커니즘 = (없음 / Render Cron / v1→운영 push / 기타)** 확정

### 2) 5/2~5/7 그 메커니즘이 왜 멈췄는지
- **(없음)**: 그렇다면 v1 로컬은 어떻게 5/10 시점 128 row 인지 (백로그 053 백필이 사이트에서 직접 받음 — 운영 stale 의 본질 원인 = sync 자동화 부재)
- **(Render Cron)**: cron 로그 확인, jbtp daily 실패 로그
- **(v1→운영 push)**: v1 cron / scheduler 로그, 5/2~5/7 동안 push 가 발생했는지

### 3) 다른 source 동시 점검
- bizinfo (10,684), kstartup (400), jbbi (362), jbexport (65~68), at_global, kseafood
- 운영 DB 의 각 source 별 최신 row created_at 확인 → 5/2~5/7 동안 누적된 source / 정지된 source 분리
- 결과: jbtp 만 정지 (H2) vs 모든 source 정지 (H1) 판별

## 해결 방향 (가설별)

### H1 인 경우 (sync 자동화 부재)
- 백로그 052 와 통합 — 공통 해결책 필요 (B+D / A)
- 임시 sync 스크립트 (053 의 sync_jbtp_v1_to_render.py 패턴) 매주 수동 실행 (단기)
- 본격: 사이트 list API 직접 호출 + Render Cron (사이트 차단 시 한국 IP proxy 필요)

### H2 인 경우 (Render IP 차단 jbtp 만)
- jbtp 만 별도 우회 — sync 스크립트 정기 실행 (053 패턴) 또는 한국 IP proxy
- 다른 source 는 기존 메커니즘 유지

### H3 (현재 우세) 인 경우 (proxy 무관 + jbtp 만 정지)
- **시기 (5/2~5/7) 와 jbtp 정지의 인과 관계 추적**
- v1/v2 release 이력 확인 — 5/2 이전에 jbtp 코드 수정 / connector 변경 / DB 스키마 변경
- 백로그 030 (connector 표준화 Phase 2 v2) 가 5/7 완주 → 그 시점 v2 jbtp connector 변경 영향 가능

## 진행 절차

### Phase 1 — 사실 수집 (자율, ~30min)
- 운영 DB 각 source 최신 row created_at 확인 (Render Shell SQL)
- v1 로컬 DB 각 source 최신 row created_at 확인 (로컬 SQL)
- 두 결과 비교 → 어떤 source 가 stale 인지 분포 확정

### Phase 2 — sync 메커니즘 식별 (자율 + 사용자)
- Render Dashboard cron jobs 확인 (사용자가 캡처)
- v1 schedule / scheduler 설정 확인
- 사용자 인터뷰: "운영 DB 가 어떻게 업데이트되는지" 멘탈 모델 확인

### Phase 3 — 가설 확정 + 해결 (사용자 stop)
H1 / H2 / H3 중 어느 것인지 확정하고 해결 방향 합의.

### Phase 4 — 해결 적용 (별도 작업)
- 임시: 053 sync 스크립트 1주일 / 매일 실행 모니터링
- 본격: 052 와 통합 또는 별도 백로그 분리

## 관련 자료

- 백로그 052: jbexport proxy/sync 자동화 (동일 chain 가능성 — 같은 본질)
- 백로그 029: v1/v2 connector divergence (5/10 시점 jbtp connector 가 v1=legacy, v2=4단계 분리 — 영향 가능성)
- 백로그 030: connector 표준화 Phase 2 v2 (5/7 jbtp 4단계 분리 완주)
- 백로그 053: jbtp 위젯 fix + Render IP 차단 우회 sync (본 백로그의 표면 증상 진단)
- release/2026-05-10_jbtp_widget_fix/sync_jbtp_v1_to_render.py: 임시 우회 (단발성, 본 백로그 본격 해결 까지 매주 모니터링)

## 메모

- 본 백로그 진단 결과에 따라 052 와 통합될 수도, 분리될 수도 있음
- 만약 H1 (sync 자동화 부재) 으로 확정되면 052 + 057 = 동일 본질 → 한 백로그로 합치고 057 close
- 5/2~5/7 동안 운영 측 daily 가 어떻게 동작했는지 확인이 핵심 — Render Dashboard / cron logs 가 1차 자료

---

# Phase 1 진단 결과 (2026-05-10)

## 핵심 발견 — deploy-004 가 sync 메커니즘 자체를 break

### 한 줄 결론
**5/4 deploy-004 가 "GitHub Actions → db/biz.db git push → Render 자동 재배포 → 운영 DB 갱신" 메커니즘을 의도적으로 끊음. 이후 운영 DB 갱신 메커니즘이 사실상 부재. 5/2~5/7 stale = 메커니즘 부재의 자연스러운 결과.**

## 코드 evidence

### 1) 5/3 까지 알려진 메커니즘 — `docs/release/deploy-002_v1.1.md` line 80~86

```
### 시스템 아키텍처
- 메일: Apps Script 매일 09:13
- 크롤링: GitHub Actions 매일 06:00
- DB: GitHub push → Render 자동 재배포
- 카톡: appy.py L2371
```

→ 5/3 시점 명문 기록: 운영 DB 는 **GitHub Actions 가 db/biz.db 를 push → Render auto-deploy 가 받아옴** 으로 갱신됨.

### 2) GitHub Actions workflow — `.github/workflows/daily-crawl.yml`

```yaml
on:
  schedule:
    - cron: "0 23 * * *"   # UTC = KST 08:00 (LATEST.md 의 06:00 기록과 차이는 별건)
jobs:
  crawl:
    steps:
      - run: python run_all.py --mode bizinfo
      - run: |
          git add db/biz.db data || true
          if git diff --cached --quiet; then ...
          else git commit -m "chore: daily auto crawl data update" && git push; fi
```

핵심 한계:
- **`--mode bizinfo` 만 실행** — `run_all.py` main() 시작에 `run_connector("JBBI"/"JBTP"/"JBTP_RELATED"/"AT_GLOBAL"/"KSEAFOOD")` 가 항상 실행되긴 하나, GitHub Actions runner 는 **해외 IP** 라 jbtp.or.kr 차단 가능성 (053 follow-up #2 패턴 동일)
- 그러나 이 한계는 **2차** — 1차는 아래 deploy-004 break

### 3) deploy-004 (2026-05-04) 의 break — `release/2026-05-04_deploy-004/MANIFEST.md`

명문 변경:
| 항목 | 변경 |
|---|---|
| Render Persistent Disk | 1GB 추가, mount `/var/data` |
| 환경변수 | `DB_PATH=/var/data/biz.db` |
| db/biz.db | 정적 사본 (11,694건 정적만, 동적 7테이블 비움) |
| ensure_db_file() | `if not target.exists()` → /var/data/biz.db 존재 시 **자동 복사 SKIP** |
| Phase 3 | `.gitignore` 에 db/biz.db 추가 + `git rm --cached` |

→ deploy-004 의 의도는 **redeploy 마다 동적 데이터(visit_log/click_log) reset 차단**. 부수효과로 **GitHub push 의 db 갱신이 운영에 도달하지 못함**.

### 4) `.gitignore` 확정 — line 18

```
# db/biz.db: 운영은 영구 disk (/var/data/biz.db) 사용 — git 추적 해제 (deploy-004)
```

git log 확인:
```
de23b77 chore(v2): db/biz.db git 추적 해제 + DR 절차 문서화 (deploy-004 Phase 3)
25522fe deploy-004 A2: db/biz.db 정적 사본 적용
```

→ 5/4 이후 daily-crawl.yml 의 `git add db/biz.db` 는 `.gitignore` 에 의해 무시됨 → `git diff --cached --quiet` 가 항상 true → **commit 자체가 일어나지 않음** → workflow 는 cron 돌더라도 실효 0.

→ **5/4 이후 daily-crawl.yml = dead workflow**.

### 5) 운영 자체 갱신 경로 — `appy.py /run` (2524) + `/api/run` (2774)

웹 앱 자체에 trigger endpoint 가 있음:
- `POST /run` → `subprocess.run(pipeline/run_pipeline.py)` (10분 timeout)
- `POST /api/run` → `_run_pipeline_background(mode)` → `run_all.py --mode <mode>` 백그라운드

`run_pipeline.py` (line 167) 흐름: bizinfo connector → merge_all → detect_new → detect_deadline → recommend → make_report_pdf → make_mail → mailer → kakao.
→ **bizinfo 만**. jbtp/jbexport/jbbi/at_global/kseafood 누락.

`appy.py:_effective_pipeline_mode()` (line 500): `RENDER` env var 있으면 `all → bizinfo` 강제. 즉 운영에서 `/api/run all` 호출해도 bizinfo 만.

### 6) 외부 trigger — 코드 내 흔적 없음

| grep 결과 | 의미 |
|---|---|
| `requests.post.*\/run` | 0 매치 — 코드 내 자기 호출 없음 |
| `crontab\|render-cron\|onrender` 호출 코드 | 0 매치 |
| `render.yaml` | 파일 없음 — Render Cron Job 설정은 dashboard 수동 등록만 가능 |
| auto_run.bat | v1 로컬 `run_all.py` 만 실행, 운영 push 0 |

→ **5/4 이후 외부에서 `/api/run` 을 매일 자동 호출하는 메커니즘 = 코드 흔적 없음**.

## 가설 판정

| 가설 | 판정 | Evidence |
|---|---|---|
| **H1** GitHub Actions / scheduled workflow | ❌ Dead (5/4~) | daily-crawl.yml 존재하나 `.gitignore` 로 git push 무효화. 5/3 까지는 정상 동작했을 가능성 |
| **H2** Render Cron Job (자체) | ❓ render.yaml 없음 | Render Dashboard 에서 별도 Cron Job 서비스 등록 가능. **사용자 확인 필요** |
| **H3** v1 로컬 → Render API push | ❌ 흔적 없음 | auto_run.bat / run_all.py / requests.post 모두 운영 도메인 호출 0 |
| **H4** 외부 트리거 (Apps Script 등) | ❓ 가능 | LATEST.md "메일: Apps Script 매일 09:13" — 메일만 트리거인지 `/api/run` 도 같이 트리거인지 **사용자 GAS 코드 확인 필요** |

## 5/2~5/7 stale 시나리오 (가설 우세)

**Timeline 재구성**:

| 일자 | 이벤트 | 운영 DB 영향 |
|---|---|---|
| ~5/3 | GitHub Actions cron + db/biz.db git push + Render auto-deploy → 운영 DB 매일 동기화 | 정상 누적 (jbtp 113 까지 도달했을 시점) |
| **5/4** | **deploy-004 적용**: Persistent disk 도입 + db/biz.db .gitignore + ensure_db_file SKIP | sync break. /var/data/biz.db 는 5/3 까지의 last state 로 동결 |
| 5/4~5/7 | GitHub Actions cron 은 돌지만 git push 무효 (gitignore). 외부 trigger 없으면 운영 DB 정지 | jbtp 113 stale, 5/4~5/7 신규 row 미반영 |
| 5/8 | 백로그 036 wrapper proxy fix (v1 only) | 영향 0 (v1 로컬만) |
| 5/9 | v1 로컬 jbtp 백필 + sync 누적으로 128 도달 | 운영 미반영 |
| 5/10 | 053 follow-up #2 — 사용자가 운영 stale 발견 → sync_jbtp_v1_to_render.py UPSERT | 운영 113 → 128 (수동 1회) |

**핵심**: 5/2~5/7 stale = "메커니즘이 멈췄다" 가 아니라 **"5/4 이후 메커니즘 자체가 사실상 부재"**. v1 만 누적되고 운영은 동결.

→ **가설 H1 (sync 자동화 부재) 우세**. 백로그 052 와 동일 본질 가능성 높음.

## Render IP 차단 (053 follow-up #2) 와의 관계

053 에서 발견: Render Shell 에서 `python backfill_jbtp.py` 실행 시 `jbtp.or.kr` ConnectTimeout. 즉 **운영 측이 daily 를 돌리려 해도 jbtp.or.kr fetch 자체 불가**.

→ 가령 사용자가 H2 (Render Cron) 또는 H4 (외부 trigger) 를 등록하더라도, jbtp 사이트는 IP 차단으로 fetch 실패. 본격 해결책 (백로그 052 옵션 B+D) 에서 **GitHub Actions / Render Cron 어느 쪽이든 IP 차단 우회 필요**.

## 운영 DB 의 다른 source 는 어떻게 채워졌나? (별도 진단 필요)

| Source | v1 로컬 | 운영(Render) 추정 | 확인 필요 |
|---|---|---|---|
| jbtp | 128 | 113 (053 sync 전) | 5/2~5/7 + 5/4~5/7 누락 |
| jbexport | 68 | 65~66 (052 sync 전) | 052 와 동일 chain |
| bizinfo | 10,684+ | ? | 5/4 이후 누적되었는지 |
| kstartup | 400 | ? | 동일 |
| jbbi | 362 | ? | 동일 |
| at_global | ? | ? | 동일 |
| kseafood | ? | ? | 동일 |

**실증 필요**: Render Shell SQL 로 운영 DB 의 source 별 `MAX(created_at)` 확인. 만약 모든 source 가 5/3~5/4 부근에서 stale 이면 **H1 우세 + 5/4 이후 메커니즘 부재 확정**. 일부 source 만 누적되면 다른 메커니즘 부분 동작 가능성.

---

# 다음 단계 권장 (Phase 2 — 다음 주)

## 즉시 (자율, ~30min)
1. **운영 DB source 별 MAX(created_at) 확인** — Render Shell SQL
   ```sql
   SELECT source, MAX(created_at), COUNT(*) FROM biz_projects GROUP BY source;
   ```
   → 5/4 이후 stale 분포 확정

## 사용자 액션 필요
2. **Render Dashboard 점검**
   - Cron Job 서비스 등록 여부 (web service 외 별도)
   - 5/4 이후 deploy 이력 (/var/data/biz.db 영향 안 받지만 기준점)
3. **Google Apps Script 코드 확인**
   - 09:13 mail 외에 `/api/run` 호출도 있는지
   - 있으면 H4 부분 인정, 없으면 H4 ❌ 확정
4. **외부 cron-as-a-service** 사용 여부 (사용자 멘탈 모델)
   - cron-job.org / EasyCron / IFTTT 등록 여부

## Phase 3 (가설 확정 후)
- H1 (sync 자동화 부재) 확정 시: **백로그 052 와 통합** → 한 백로그로 합치고 057 close
- H2 (Render Cron 부분 동작) 확정 시: jbtp 만 별도 IP 차단 우회 (053 sync 패턴 정기 실행) + 다른 source 는 기존 메커니즘 유지
- 본격: 052 옵션 B (사이트 list API 직접 호출, IP 차단 우회) + D (Render Cron 또는 GitHub Actions 한국 IP proxy)

## 임시 조치 (모니터링)
- 053 의 `sync_jbtp_v1_to_render.py` UPSERT 패턴을 매주 1회 수동 실행
- 052 의 `sync_two_rows.py` 도 jbexport 매주 1회 수동 실행
- Phase 3 본격 해결 까지의 단기 buffer

---

# Phase 2 정식 명세 (2026-05-11 결정)

## 5/11 핵심 발견 — Phase 1 진단 일부 정정

Phase 1 (5/10) 의 우세 가설은 "deploy-004 (5/4) 가 GitHub Actions 의 db git push 를 `.gitignore` 로 무효화 → sync break". 5/11 실제 확인 결과 **부분 정정** 필요.

### Evidence

1. **GitHub Actions cron 매일 정상 실행**
   - workflow runs #5 (5/4) ~ #12 (5/11) 모두 success
   - 즉 cron job 자체는 멈춘 적 없음

2. **`.github/workflows/daily-crawl.yml` 의 마지막 step 에 5/3 의식적 disabled 주석 존재**
   ```yaml
   # DISABLED 2026-05-03: DB auto-push removed to prevent overwriting
   # dynamic tables (click_log, visit_log, companies, user_request_log,
   # recommendations)
   ```
   → deploy-004 (5/4) 가 `.gitignore` 로 끊은 게 아니라, **5/3 시점에 의식적으로 마지막 step (`git add db/biz.db && git push`) 자체를 disable** 한 것.

3. **사용자 PC daily run (Win Task 20:37) = v1 로컬 누적 master**
   - 매일 사용자 PC 에서 `auto_run.bat` (백로그 036) 가 wrapper → `run_all.py` 전체 mode 실행
   - 결과는 **v1 로컬 DB 에 누적**
   - GitHub Actions runner (해외 IP) 대신 **사용자 PC (한국 IP)** 가 사이트 fetch 담당 — IP 차단 영향 0

4. **운영 DB stale 진짜 원인 = Actions 가 결과 폐기 (의도적 보호)**
   - Actions 는 매일 crawl 까지는 수행하나 결과를 git push 하지 않음
   - 즉 운영 DB 갱신 메커니즘은 **5/3 시점부터 의도적으로 부재**
   - 동적 테이블 (click_log/visit_log/companies/user_request_log/recommendations) 덮어쓰기 방지 = 5/3 결정의 정당한 이유

### Phase 1 진단표 갱신

| 가설 | 5/10 판정 | 5/11 갱신 |
|---|---|---|
| H1 GitHub Actions sync 자동화 부재 | ✅ 우세 (5/4 deploy-004 break) | ✅ 확정 (단, 시작은 **5/3 의식적 disable**, deploy-004 는 사후 보강) |
| H2 Render Cron Job 자체 | ❓ render.yaml 없음 | ❌ (의식적으로 안 만든 것) |
| H3 v1 로컬 → Render API push | ❌ 흔적 없음 | ❌ 확정 |
| H4 외부 트리거 (Apps Script 등) | ❓ | ❌ (mail 만 trigger, /api/run 호출 없음) |

→ **본질 = "운영 DB 갱신 메커니즘이 의식적으로 부재한 상태"**. 5/3 결정 (동적 테이블 보호) 의 정당성은 유지하되, **정적 데이터 (biz_projects) 만 선택적으로 sync 하는 새 메커니즘** 필요.

---

## 채택: 옵션 A — Incremental Sync

### 배경

| 옵션 | 내용 | 평가 |
|---|---|---|
| B | 정적/동적 테이블 분리 (별도 DB 또는 별도 service) | 큰 리팩토링 + 마이그레이션 위험 → W22 이후 |
| **A** | **/api/sync 엔드포인트로 정적 데이터만 incremental sync** | **1주 작업, 즉시 정상화 가능, 5/3 동적 보호 정책 유지** |

→ **A 채택**. B 는 장기 옵션으로 별도 백로그.

### 핵심 정책 (5/10~5/11 결정)

1. **Incremental sync** — 변경분만 동적 sync (full row dump X)
2. **url unique 기준 UPSERT** — biz_projects.url 을 unique key 로
3. **연번 (notice_order) ≠ sync 기준** — 위젯 정렬용일 뿐, sync delta 추적에 사용하지 않음
4. **`synced_to_render` flag 로 delta 추적** — 0=미동기 / 1=동기됨
5. **Empty payload skip** — sync 대상 row 0 건 → API 호출 자체 skip (noise 감소)
6. **동적 테이블 절대 안 건드림** — click_log / visit_log / companies / user_request_log / recommendations (5/3 정책 유지)

> 5/10 일지의 "연번 기반 incremental sync" sketch 는 **5/11 정책 #3 으로 정정**. 연번은 위젯 표시 정렬에만 사용. sync delta 는 `synced_to_render` flag 가 단일 source-of-truth.

## Phase 2.1 — /api/sync 엔드포인트 (모든 source 공통)

운영 측 `appy.py` 에 신규 엔드포인트 추가:

```python
@app.route('/api/sync', methods=['POST'])
def api_sync():
    # 1. ADMIN_KEY 인증
    if request.headers.get('X-Admin-Key') != os.getenv('ADMIN_KEY'):
        return jsonify({'error': 'unauthorized'}), 401

    # 2. body: { source, rows: [...] }
    data = request.get_json()
    source = data.get('source')
    rows = data.get('rows', [])

    if not source or not rows:
        return jsonify({'error': 'missing source or rows'}), 400

    # 3. url unique 기준 UPSERT (biz_projects 만)
    conn = sqlite3.connect(DB_PATH)
    try:
        inserted = updated = 0
        for row in rows:
            url = row.get('url')
            if not url:
                continue
            existing = conn.execute(
                'SELECT id FROM biz_projects WHERE url=?', (url,)
            ).fetchone()
            if existing:
                # UPDATE (049 merge 보호 패턴 적용)
                updated += 1
            else:
                # INSERT (full row)
                inserted += 1
        conn.commit()
    finally:
        conn.close()

    # 4. 동적 테이블 (click_log/visit_log/...) 절대 안 건드림
    # 5. 응답: { inserted, updated, count }
    return jsonify({
        'source': source,
        'inserted': inserted,
        'updated': updated,
        'count': len(rows),
    })
```

### 설계 포인트

- **`biz_projects` 만 대상**. 동적 테이블 6종 모두 미터치 (정책 #6)
- **`url` unique** — 이미 053 sync 스크립트에서 검증된 패턴
- **`UPDATE` 시 049 merge 보호 패턴 적용** — 운영 측에 이미 채워진 필드 (예: ai_summary, organization 백필) 를 v1 dump 가 덮어쓰지 않도록 보호 (구체 컬럼 화이트리스트는 Phase 2.2 에서 확정)
- **응답 통계** — inserted/updated/count 로 호출자가 결과 검증
- **`source` 파라미터** — 1회 호출에 1 source 만. 멀티 source 는 호출자가 source 별로 순차 호출

### 호출자 (v1 로컬 측)

별도 스크립트 `pipeline/sync_to_render.py` (가칭) — `run_all.py` 완료 후 호출:

1. v1 로컬 DB 에서 `WHERE synced_to_render=0` row 조회
2. source 별로 그룹핑 → 각 source 별 `/api/sync` POST
3. 응답 OK → 해당 row 들의 `synced_to_render=1` UPDATE
4. 실패 (network / 401 / 500) → flag 갱신 X → 다음 실행 시 재시도 (멱등성)

### 변경 범위

| 항목 | 변경 |
|---|---|
| v2 `appy.py` | `/api/sync` 엔드포인트 신규 추가 |
| v2 `db/schema.py` (또는 migrate) | `biz_projects.synced_to_render INTEGER DEFAULT 0` 컬럼 추가 |
| v2 `pipeline/sync_to_render.py` | 신규 스크립트 (v1 로컬 → Render push) |
| v2 connectors | INSERT 시 `synced_to_render=0` 명시 (대부분 default 로 충족) |
| v2 `appy.py` `/api/run` 등 update 경로 | UPDATE 시 `synced_to_render=0` 으로 reset (변경분 재sync) |
| `.github/workflows/daily-crawl.yml` | **변경 0** (5/3 disable 정책 유지). Actions 는 그대로 crawl 만 하고 결과 폐기 |
| v1 `auto_run.bat` (036) | `run_all.py` 완료 후 `sync_to_render.py` 호출 step 추가 |
| 운영 deploy | 신규 엔드포인트 + 스키마 migrate 적용 |

### 단계

1. Phase 2.1a — v2 에 스키마 컬럼 추가 + migrate 스크립트
2. Phase 2.1b — v2 `appy.py` `/api/sync` 구현 + 단위 테스트
3. Phase 2.1c — v2 `pipeline/sync_to_render.py` 호출자 구현
4. Phase 2.1d — 로컬 시뮬 (v1 사본 DB → v2 dev appy `/api/sync`) 검증
5. Phase 2.1e — release/ 후보 등록 → v1 cherry-pick → 운영 deploy
6. Phase 2.1f — auto_run.bat 에 sync_to_render.py step 추가 → 1주 모니터링

### 합쳐질 백로그

- **052 (jbexport proxy/sync 자동화)** — 본질 동일 (운영 DB sync 메커니즘 부재). Phase 2 완료 시 close
- **053 sync_jbtp_v1_to_render.py** — Phase 2 의 prototype. 정식 sync 도입 후 retire (또는 임시 fallback 유지)

### W19 외 후속 (W20+)

- Phase 2.2 — UPDATE merge 보호 컬럼 화이트리스트 확정 (049 패턴 확장)
- Phase 2.3 — sync 실패 알림 (kakao / mail)
- Phase 2.4 — 동기화 통계 대시보드 (마지막 sync 시각, source 별 pending row 수)
