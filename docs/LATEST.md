# LATEST — BizGovPlanner 진입점

**사이클**: 5/3 deploy-002 → Phase 3.0 PoC 완료 (5/20 Step 1~4, 검증 성공)
**마지막 갱신**: 2026-05-21 (Phase 3 본 구현 ①② 완료 — enrich 영구화 + status 재분류)

---

## 🟢 시스템 상태

| 항목 | 상태 | 비고 |
|---|---|---|
| 운영 사이트 | 🟢 정상 | https://job-bizgov-platform.onrender.com |
| 메일 발송 | 🟢 정상 | Apps Script 09:13 |
| 자동 크롤링 | 🟢 정상 | PC daily 20:37 |
| DB | 🟢 4,781 row | bizinfo 3,040 / kstartup 608 / jbbi 373 / kseafood 244 / at_global 207 / jbtp 157 / jbtp_related 79 / jbexport 73 |
| Phase 3 | 🟢 본 구현 ①② 완료 | PoC(Step 1~4) + enrich 영구화 + status 재분류 — bizinfo 확인필요 2,302→905 (−61%) |

---

## 📅 17일 작업 누적 (5/4 ~ 5/20)

### 5/4 ~ 5/9 — git 활동 없음
- 커밋 부재 구간 (deploy-002 후 검증 / 휴지 기간)

### 5/10 ~ 5/11 — b053 jbtp 백필 + b057 Phase 2.1 deploy
- **b053**: jbtp notice_order 백필 스크립트, Render IP 차단 우회 sync, sync UPSERT 확장 (snapshot dump)
- **b057**: Phase 2.1 — Incremental Sync 명세(옵션 A 채택), `/api/sync` + `sync_to_render` + `synced_to_render`/`synced_at` 컬럼 deploy (v2 cherry-pick)

### 5/12 — 사고 5건 마라톤 (11시간, 모두 해결 · 데이터 손실 0)

| # | 사고 | 원인 | 처리 |
|---|---|---|---|
| 1 | 5/11 신규 jbexport 운영 위젯 미반영 | `merge_jb.py` notice_order drop | 3 패치 + v1·운영 즉시 sync |
| 2 | jbtp connector 1차 실행 중복 INSERT 117건 | 사이트 url 파라미터 순서 변경 미인지 | 백업 복원 + surgical url 정규화 |
| 3 | `backfill_jbtp.py` DRY_RUN 미적용 | PowerShell `$env:` 문법 Bash 툴 미주입 | 의도와 결과 일치 + 스크립트 백업 활용 |
| 4 | Render sync 403 | ADMIN_KEY env 미상속 | 사용자 1회 키 주입 |
| 5 | #1 dry-test 4 connector 893 row 중복 INSERT | 4 connector 동일 url 결함 | 백업 복원 + #1 보류 + 백로그 064 신설 |

- 모두 백업 복원으로 **데이터 손실 0**
- 사이클 분리(064 → #1) 효과로 한밤중 2차 작업은 사고 0회

### 5/13 — 자동화 6항목 검증
- PC daily run 20:37:58 정시 fire
- DB 변동: bizinfo +1,246 / jbtp +2 / jbexport +1
- at_global 멱등성 결정적 증거 (시도 205 / 신규 0 / 중복 205)
- sync step 누락 발견 (`auto_run.bat`)
- 백로그 065 Phase 2-A 진단 종료, 사용자 결정 4건

### 5/14 ~ 5/17 — 백로그 진행 + AI 언어 통역 기능
- 백로그 064 Phase 2-B (kseafood URL Base64 백필)
- 백로그 065 Phase 2-B (스키마 단일 출처 통합, `sync-to-render --dry-run` 제거 → 본 실행 활성화)
- v2 cherry-pick 적체 해소
- b066 AI 친화 통역 모듈 + `ai_friendly_title/summary`, b069 Phase 2 `ai_summary` backfill
- 시뮬 누적 시스템 정착 (`docs/simulations/INDEX.md` 신설)

### 5/18 ~ 5/20 — 박람회 + Phase 3.0 PoC
- **5/18**: 박람회 첫날 (코리아 씨푸드 쇼 D07)
- **5/19**: Phase 3.0 PoC Step 1+2 — 코드 read + DRY-RUN 90%, 12번째 가설 정정 4건
- **5/20**: 박람회 마지막 날 + Phase 3.0 PoC Step 3 본 실행 — 부분 성공 35.8% (네트워크 실패 57.4%), 5/22 재실행 결정

---

## ⚙️ Phase 3.0 PoC 현황 — ✅ 완료 (5/20)

| Step | 상태 | 결과 |
|---|---|---|
| Step 1 코드 read | ✅ | `--enrich-detail` 명세 4건 정정 (위험 E: JSON-only, DB 미접근) |
| Step 2 DRY-RUN 10건 | ✅ | fetch 10/10, end_date 9/10 = 90% |
| Step 3 본 실행 | ✅ (부분) | 5/20 오전 박람회장 — 네트워크 823건 실패, 513건 성공 |
| Step 3 재실행 | ✅ | 5/20 밤 안정 네트워크 — fetch 1,474/1,474, 실패 0 |
| Step 4 JSON→DB merge | ✅ | merge_jb → update_db, 입력 4,600 실패 0 |

### PoC 정량 결과
- DB bizinfo **확인 필요 2,302 → 1,446 (−856, −37%)**, end_date 738 → 1,500 (+762)
- 파싱 정확성 100%, 무마감 공고 48.1% (정당 추출)
- **13번째 가설 정정**: enrich 결과 비영구 (야간 wipe) → Phase 3 본 구현 = "영구화"

### ✅ Phase 3 본 구현 — ①② 완료 (5/21, commit `44c20b0`)

| 백로그 | 변경 파일 | 결과 |
|---|---|---|
| ② status 재분류 | `normalize_project.py` | `infer_status` 무마감 키워드 정정 (공백 버그 + "선착순") → bizinfo 확인필요 1,446 → 905 (−541) |
| ①B wipe 차단 | `update_db.py` | `_upsert_one` UPDATE에 end_date 보존 가드 — 가드 테스트 통과 |
| ①A enrich 자동화 | `run_pipeline.py` | 야간 파이프라인에 `--enrich-detail` 통합 (crawl→enrich→merge→update_db) |

- **옵션 C(야간 wipe 허용) 해소** — ①A+①B로 야간 run이 wipe 대신 enrich+보존, PoC 결과 매일 자동 유지
- 누적: bizinfo 확인 필요 **2,302 → 905 (−61%)**
- 야간 run +25~30분 (enrich HTTP) — 5/21 20:37 = 첫 라이브 통합 실행
- DB 롤백 지점: `db/biz.backup.20260521_001650_pre_phase3_impl.db`
- 검증: infer_status 단위테스트 + end_date 가드 테스트 + update_db 재실행 (실패 0)

---

## 🔒 절대 원칙

- v1 (`hover9710-beep/Job-bizgov-platform`, 운영) 코드 직접 수정 금지
- v2 (`hover9710-beep/Job_bizgov_platform_dev`, 개발) — release → cherry-pick
- `git commit` / `git push` 는 사용자 직접 (명시 지시 시 예외)
- Python 명령은 `py`
- PowerShell 코드블록 한국어 / 이모지 금지
- ADMIN_KEY 채팅 / 로그 / 파일 노출 X
- **신규 — 사전 점검 + 누적 자산 패턴 표준화** (디버깅 인프라: 백업 · DRY-RUN · 차단 체크리스트)
- **신규 — 멱등성 우선** (재실행 안전, `WHERE` / `skip_if_has` 가드)
- **신규 — 박람회장 등 네트워크 불안정 환경에서 본 실행 금지**

---

## 🚀 다음 세션 시작 명령

```
@docs/LATEST.md 읽고 5/22 야간 파이프라인 통합 run 결과 검증
— 5/21 20:37 crawl→enrich→merge→update_db 정상 작동 확인
— DB bizinfo end_date·확인필요 유지 검증 (wipe 없이 enrich 반영)
```

| 일자 | 작업 | 상태 |
|---|---|---|
| 5/20~5/21 | Phase 3.0 PoC (Step 1~4) | ✅ 완료 |
| 5/21 | Phase 3 본 구현 ①② (enrich 영구화 + status 재분류) | ✅ 완료 |
| 5/21 20:37 | 야간 파이프라인 첫 통합 run (enrich 자동화) | ⏳ |
| 5/22 | 야간 run 결과 검증 (end_date 유지 확인) | ⏳ |
| 5/24 (일) | 광주 공모전 마감 (보류 검토) | ⏳ |
| 7/3 (목) | 전북 공모전 (JBTP) 마감 | ⏳ |

---

## 관련 파일

- PoC 완료 데일리: `docs/daily/2026-05-22_phase3_poc_completed.md`
- PoC 완료 회고: `docs/simulations/2026-05-20_phase3_poc_completed.md`
- 5/20 데일리: `docs/daily/2026-05-20.md`
- Phase 3.0 Step 1+2: `docs/daily/2026-05-20_phase3_poc_step1_2.md`
- PoC 사전 시뮬: `docs/simulations/2026-05-19_phase3_poc_pre_simulation.md`
- 백로그: `docs/backlog/enrich_persistence.md`, `docs/backlog/no_deadline_classification.md`
- 5/17 마라톤 종합: `docs/daily/2026-05-17_bizgov_marathon.md`
- 시뮬 INDEX: `docs/simulations/INDEX.md`
- release INDEX: `release/INDEX.md`
