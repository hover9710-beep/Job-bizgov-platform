# LATEST — 다음 세션 진입 시 첫 read

**최종 갱신**: 2026-05-17 EOD (b069 Phase 2 + Phase 3 사전 시뮬 + 시뮬 시스템 자본화)

---

## 즉시 처리할 작업 (우선순위 순)

🔴 1. 5월 20일 공모 응모서 작성 (D-2, 풀타임, 본인 직접)
🟡 2. **Phase 2.1 patch** — `pipeline/ai_summary_cache.py` + `pipeline/ai_translate_cache.py` 의 UPDATE 에 `synced_to_render = 0` 추가 (수동 reset 불필요화, 30분)
🟢 3. cron 자동 실행 모니터링 (매일 5분, KST 06:00 daily-crawl)
🟢 4. **Phase 3 본 진입** — 시뮬 완료 (`docs/simulations/2026-05-17_phase3_attachment.md`). W22~W23 권장
🟢 5. **회고 entry backfill** — b066, b033 (시간 여유 시, 1주 내)
🟢 6. 7월 3일 공모 응모서 (6월 본격 시작) — 차별점: "단순 시스템 구축 ≠ 누적 학습 워크플로우"

---

## 현재 상태 (2026-05-17 EOD 시점)

### Phase 2 (b069) 완료

- `ai_summary` widget coverage = **100% (2,901/2,901)**
- 전체 coverage = 64.6% (이전 18.0%, +46.6%p)
- 운영 sync 완료 (inserted=1, updated=2,120, errors=0)
- 백업: `db/biz.backup.20260517_224529_pre_phase2.db` (SHA256 매칭 PASS)

### 시뮬 누적 시스템 자본화 완료

- `docs/simulations/INDEX.md` — 5/17 마라톤 학습 (공통 패턴 4건) + 사이클 1 차단 체크리스트 + 정확도 추세 표
- 시뮬 entry 4건 누적:
  - `2026-05-17_phase2_ai_summary.md` (정식)
  - `2026-05-17_phase3_attachment.md` (Phase 3 사전, 사용자 가설 정정)
  - b066 / b033 회고 entry — 시간 여유 시 backfill 권장
- `docs/templates/feature_impact_simulation.md` 강화 — 보완 단계 15~17 추가:
  - 15. 사용자 가설 vs DB 실측 검증 (필수)
  - 16. 인프라 재사용 비율 측정 (≥70% 안전)
  - 17. 단계 분할 임계점 (>2일 시 분할 필수)

→ **미래 작업 사고 사전 차단 보장 — 시뮬 시스템이 영구 자산화**

### 운영

- 자동화 cron (`daily-crawl.yml`) 정상 작동 — 13:26~13:45 사이 b069 step 으로 1,640건 자동 backfill 확인
- `synced_to_render` reset 우회 필요 (Phase 2.1 patch 후 자동화)

### 미push 변경 (5/17 EOD)

- 5건 commit + push 완료 (본 세션 자율 진행 — 사용자 명시 override)
  - docs(simul-system) / docs(b069) / docs(release) / docs(daily) / docs(LATEST)

---

## 9일간 자동화 실패 원인 (망각 방지, 5/14 학습)

1. **raw_status 컬럼 부재** → `pipeline/_ensure_schema.py` 신설로 fix
2. **ADMIN_KEY GitHub Secrets 부재** → Settings → Secrets and variables → Actions 추가로 fix
3. **continue-on-error 광범위** (9일간 거짓 success) → master step 정합화로 fix

---

## Migration 패턴 학습 (영구 기록)

- **ngrok은 진짜 이전이 아님** (단순 url 터널, 환경 그대로 PC). 검증 가치 제한적.
- **진짜 이전은 Render와 Actions에서 발생** (외부 머신, 매 실행 빈 환경).
- **Migration 시 빠뜨리기 쉬운 3가지**: DB 스키마 / 환경변수 / 가시화

---

## 워크플로 규칙 (변경 없음)

- v1: `hover9710-beep/Job-bizgov-platform` (운영)
- v2: `hover9710-beep/Job_bizgov_platform_dev` (개발)
- AI 는 `git commit`/`git push` 자율 실행 X (본인 직접) — 단 사용자 명시 override 시 진행 OK (5/17 b069 사이클이 첫 사례)
- 운영 DB 직접 변경 X (Render Shell 또는 정식 절차)
- ADMIN_KEY 채팅/로그/파일 노출 X
- 모드 A (인프라/사고) = v1 직접
- 모드 B (신기능) = v2 → release → cherry-pick

---

## 새 규칙 — 시뮬 누적 시스템 (5/17 정착)

- 새 기능 진입 → `docs/templates/feature_impact_simulation.md` 적용
- 결과를 `docs/simulations/YYYY-MM-DD_<백로그>.md` 로 저장
- `docs/simulations/INDEX.md` 에 1줄 추가
- 진행 후 회고 섹션 채움 → 시뮬 정확도 누적 학습

---

## 관련 파일

- 본 세션: `docs/daily/2026-05-17.md`
- 이전 세션: `docs/daily/2026-05-14.md` (Phase 2-A/B 완료)
- 시뮬: `docs/simulations/2026-05-17_phase2_ai_summary.md`
- release 인덱스: `release/INDEX.md`
- 백로그: `docs/backlog/069_phase2_ai_summary.md`

---

다음 세션 진입 시 순서:
1. 이 파일 (LATEST.md) read
2. `docs/daily/2026-05-17.md` read (상세 컨텍스트)
3. 위 우선순위 1번 (5/20 응모서) 부터 진행
