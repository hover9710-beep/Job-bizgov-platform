# 배포확정 폴더 인덱스

## 누적 배포 후보 목록 (최신순)

| 날짜 | 폴더 | 핵심 변경 | 배포 상태 |
|---|---|---|---|
| 2026-05-17 EOD | [2026-05-17_b069_phase2_ai_summary](./2026-05-17_b069_phase2_ai_summary/) | b069 Phase 2 AI 한줄요약 완비 — `ai_summary` widget coverage **100%** (2,901/2,901), 전체 18.0% → 64.6% (+46.6%p). backfill (`--widget-targets`, pending=1 generated, 선행 cron 누적 2,121건) + `synced_to_render` 수동 reset + `sync_to_render.py` 실행 (inserted=1, updated=2,120, errors=0, 7 source). 비용 ~$0.10. 사후 발견: `ai_summary_cache.py` UPDATE 가 sync flag reset 안 함 → Phase 2.1 patch 필요. 시뮬 entry + INDEX 시스템 정착 (3번째 entry). | 🟢 운영 sync 완료 (Render auto-deploy) |
| 2026-05-14 | (commit only) | 백로그 065 Phase 2 (Pre/A/B) 코드 작성 — 모드 A 인프라 정비 (v1 직접). Phase 2-Pre: `pipeline/_ensure_schema.py` 신설 (36 컬럼 통합 idempotent ALTER, 4 테이블) + 4 import (at_global / kseafood / jbexport_daily / update_db). v1 로컬 DB 멱등 검증 PASS (added=0, SHA256 변동 0), Actions runner 빈 DB 시뮬 PASS (added=34). Phase 2-A: `.github/workflows/daily-crawl.yml` 의 8 crawler step `id:` 추가 + summary 전체 재작성 (`if: always()` + master 실패 시 exit 1, aux 실패는 WARN 만). Phase 2-B: schema ensure step 신설 (c-light) + `/api/sync --dry-run` step 신설 (`secrets.ADMIN_KEY`) + summary critical 판정 확장 + timeout 60→75분. 사용자 결정 4건 모두 반영. **사고 0, Phase 단위 명확 분리**. 사용자 commit/push/Secret/trigger 단계 수동 대기. | 🟡 사용자 commit 대기 → push → Secrets `ADMIN_KEY` 추가 → workflow_dispatch dry-run trigger → 결과 분석 |
| 2026-05-13 | [2026-05-13_b065_phase2a](./2026-05-13_b065_phase2a/) | 5/13 자동화 검증 1차 PASS — run_aux 4 connector 자동 호출 ✅, at_global 205/0/205 idempotent 결정적 (b064 실효성 검증). #4 Render sync 미발동 — auto_run.bat sync step 누락 확인 (운영 위젯 jbtp top=20248 5/12 그대로). 백로그 065 Phase 2-A 진단 종합 종료 — raw_status 사용 범위 + `_safe_add` 5건 누락 + yaml 진단 8건 + sync_to_render.py 인터페이스 (env `ADMIN_KEY`+`RENDER_URL`+`DB_PATH`, POST body-auth, exit code fatal-only 1). 사이클 분리 완벽 — 사고 0, fix 0, code commit 0. Phase 2-B 스코프 5건 (W20 진입 대기). 회고 섹션 추가 — 9일간 못 본 구조적 원인 5가지 (AI 시야/책임/교차검증/Cursor/빚 침묵) + 향후 패턴 3개 (스키마 단일 출처 / `docs/tech_debt.md` / `.cursorrules` 환경 명시) + v1/v2 모드 분리 (A 인프라/사고 = v1 직접, B 신기능 = v2→release→cherry-pick). docs only. | 🟡 docs commit 대기 (사용자 결정 4건 후) |
| 2026-05-12 (새벽) | (docs only) | 5/12 새벽 daily 추가 — PC 스케줄러 실험용 정정 + 자동화 부재 진단 (v1 `d879ae9`). 백로그 065 신설 — Actions `/api/sync` 통합 (5/3 disable 의 진짜 대체) (v1 `9535417`). 다음 사이클 (W20) 작업 정의 — 코드 변경 0 | 🟢 v1 push 완료 / v2 cherry-pick 완료 (daily `666a5f7`, 065 `4a9fd16`) |
| 2026-05-12 (한밤중 2차) | (commit only) | b064 Phase 2 (3 connector url 정규화) + #1 scheduler 활성화 (4 connector run_aux_crawlers 자동 호출) (v1 `9b9398a`). kseafood Phase 2-B 잔존 | 🟡 v1 push 진행 / v2 cherry-pick 보류 (Phase 2-B 와 함께) |
| 2026-05-12 (한밤중 1차) | (commit only) | b029 jbtp connector 통째 sync (4단계 분리 + _common 도입 + url 정규화 통합) (v1 `fd79792`). #1 scheduler dry-test 에서 4 connector url 변경 결함 발견 → 백로그 064 신설, #1 보류 | 🟢 v1 push 완료 / v2 cherry-pick 보류 (064 완료 후) |
| 2026-05-12 (밤) | [2026-05-12_b057_v2_cherrypick](./2026-05-12_b057_v2_cherrypick/) | b057 Phase 2.1f follow-up — jbtp 사이트 url 파라미터 순서 변경 대응 + v1 connector url 정규화 + 누적 137건 갱신 + Render sync (v1 `0032f32`+`06c02fe`, v2 patch export) | 🟢 v1 push 완료 / v2 cherry-pick docs (0002) `f7ff1fd` push 완료 / 코드 (0001) 보류 (064 와 함께) |
| 2026-05-12 (저녁) | (commit only) | b057 Phase 2.1e Step E + merge_jb notice_order drop fix (v1 `75d5265` / v2 `47ebdf3`) | 🟢 배포 완료 (Render auto-deploy) |
| 2026-05-05 | [2026-05-05_aT-connector](./2026-05-05_aT-connector/) | aT 글로벌 커넥터 추가 (200건, 백로그 024) | 🟡 v1 push 대기 |
| 2026-05-04 | [2026-05-04_deploy-004](./2026-05-04_deploy-004/) | 영구 disk 전환 + db/biz.db 정적 사본 | 🟡 v1 cherry-pick 대기 |
| 2026-05-02 | [2026-05-02_run_security](./2026-05-02_run_security/) | /run 보안 패치 | 🟡 대기 |

## 배포 워크플로우
1. 배포확정 폴더에서 적용할 항목 선택
2. v1 백업 (backup/deploy_YYYYMMDD_HHMMSS/)
3. v1 vs release/ diff 확인
4. v1에 수동 적용
5. 검증 (MANIFEST.md의 검증 절차 따름)
6. 사용자 직접 git commit + push
7. Render 자동 배포 확인
8. MANIFEST.md의 배포 상태 업데이트
9. INDEX.md의 배포 상태 업데이트

## 원칙
- ❌ 모두 배포 절대 금지 (선택적 cherry-pick)
- ✅ 배포 전 항상 백업 (날짜별 별도 보관)
- ✅ git 항상 업데이트 (배포 이력 추적)
