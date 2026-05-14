# LATEST — 다음 세션 진입 시 첫 read

**최종 갱신**: 2026-05-15 EOD (Phase 2-B `--dry-run` 제거 완료 — 본 실행 전환)

---

## 즉시 처리할 작업 (우선순위 순)

🔴 1. 5월 20일 공모 응모서 작성 (D-5, 풀타임, 본인 직접)
🔴 2. bizinfo 8,018건 중복 정리 (Render Shell, 1~2시간) — 5/16 추천
🟡 3. at_global 위젯 정렬 fix (1시간) — 5/17 추천
🟢 4. cron 자동 실행 모니터링 (매일 5분)
🟢 5. 7월 3일 공모 응모서 (6월 본격 시작)
🟢 6. (보류) 백로그 035 표준 포맷, v2 sync 등 — 공모 두 개 후
추가매일 1. cron 자동 실행 모니터링 (2026-05-15 새벽 KST 06:00)
   - 사람 개입 없이 정상 도는지 확인 — 본 자동화 완성의 진짜 신호
   - 매일 아침 Actions 페이지 5분 확인

작업:
- 🟨 본인: Actions → daily-crawl → Run workflow 수동 트리거 → 결과 확인 → 운영 DB sync 검증

검증 기준:
- workflow status = Success
- sync-to-render step log에 `pending N rows synced` 표시 (dry-run 메시지 없음)
- 운영 사이트 위젯 새 데이터 반영 확인

### 🟡 2. cron 자동 실행 모니터링 (내일 KST 06:00)

2026-05-16 새벽 KST 06:00 자동 실행 결과 확인. 사람 개입 없이 정상 도는지가 본 자동화 완성 신호.

### 🟡 3. v2 cherry-pick

Phase 2 변경 (`_ensure_schema.py` 신설 + yaml 정합화 + import 4 + dry-run 제거) → v2 backport. 모드 A이지만 일관성 차원.

### 🟢 4. 후순위 작업

- 백로그 030 v1 sync (Phase 2 connector 4종 정식 cherry-pick)
- 백로그 031 운영 적용 (`release/2026-05-07_bizinfo-dedup-033/`, 8,018건 정리)
- 백로그 035 공통 표준 포맷 도입 (엑셀 작성 진행 중)

---

## 현재 상태 (2026-05-15 EOD 시점)

- **자동화**: 9일간 실패 → 복구 완료. dry-run PASS run 25866532889 확인 후 본 실행 전환.
- **push 상태**: 최신 main = `b21518b` (v1) — sync-to-render `--dry-run` 제거 반영
- **미push 변경**: 없음
- **운영 DB**: 변경 없음 (다음 workflow_dispatch 본 실행에서 sync 시작 예정)


---

## 9일간 자동화 실패 원인 (망각 방지)

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
- AI는 `git commit`/`git push` 자율 실행 X (본인 직접)
- 운영 DB 직접 변경 X (Render Shell 또는 정식 절차)
- ADMIN_KEY 채팅/로그/파일 노출 X
- 모드 A (인프라/사고) = v1 직접
- 모드 B (신기능) = v2 → release → cherry-pick

---

## 관련 파일

- 본 세션: `docs/daily/2026-05-14.md`
- 이전 세션: `docs/daily/2026-05-13.md` (사용자 결정 4건 기록)
- release 인덱스: `release/INDEX.md`
- 백로그: `docs/backlog/065_*.md`

---

다음 세션 진입 시 순서:
1. 이 파일 (LATEST.md) read
2. `docs/daily/2026-05-14.md` read (상세 컨텍스트)
3. 위 우선순위 1번부터 진행
