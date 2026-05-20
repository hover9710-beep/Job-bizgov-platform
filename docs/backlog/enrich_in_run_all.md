# 백로그 — enrich 단계를 run_all.py(실제 야간 경로)에 통합

> **신설**: 2026-05-21 (14번째 가설 정정 — ①A 오배치 발견)
> **우선순위**: 높음
> **예상 시간**: 1~2h
> **선행**: `docs/backlog/enrich_persistence.md` (①, 방법 A 재작업분)
> **상태**: ✅ **완료 (2026-05-21, commit `db5f6bb`)**

---

## ✅ 완료 (2026-05-21)

- `run_all.py` `run_bizinfo()`에 `run_bizinfo_enrich()` 추가 — 크롤 직후 `--enrich-detail` 실행 (non-fatal). `--mode all`·`--mode bizinfo`(GHA) 양쪽 적용.
- `daily-crawl.yml` — `crawl-bizinfo` timeout 15→45분, job 95→120분.
- 검증: `run_all.py --mode bizinfo` → "2a) BIZINFO enrich-detail" 단계 작동, enrich 1,427건 0 실패, DB end_date 1,500 유지, 전 단계 exit 0.
- ⚠️ GHA 러너 enrich(클라우드 IP, 1,400+ 요청)는 런타임 검증 미완 — `workflow_dispatch` 수동 트리거 1회 권장.

---

## 문제 (14번째 가설 정정)

Phase 3 본 구현에서 ①A(enrich 자동화)를 `pipeline/run_pipeline.py`에 추가했으나,
**`run_pipeline.py`는 운영 경로가 아니다.**

| 경로 | 실행 스크립트 | enrich 포함? |
|---|---|---|
| PC 야간 스케줄러 (Task `bizplnner`, 20:37) | `auto_run.bat` → **`run_all.py`** | ❌ |
| GitHub Actions (`daily-crawl.yml`, 06:00 KST) | **`run_all.py --mode bizinfo`** | ❌ |
| 수동 웹 버튼 (`appy.py` `POST /run`, "파이프라인 실행") | `run_pipeline.py` | ✅ (①A가 여기 들어감) |

→ enrich가 수동 웹 버튼에서만 작동. **야간 자동 enrich 안 됨** → 신규 공고 end_date 미보강.
(`auto_run_backup_2026-04-05.bat`엔 `run_pipeline.py`가 있으나 현재 `auto_run.bat`은 `run_all.py`로 전환됨.)

`run_all.py` 흐름: `run_bizinfo()`(plain crawl) → `_post_merge_steps`(filter_recommend → merge_sources → diff_new → merge_jb → update_db → kstartup --sync-status-only). **enrich 단계 없음.**

---

## 해결 명세

### 1. `run_all.py`에 enrich 단계 추가

- `run_bizinfo()` (run_all.py) 직후 `connector_bizinfo.py --enrich-detail` 호출
- `run_bizinfo()` 내부에 넣으면 `--mode all`·`--mode bizinfo`(GHA) 양쪽 모두 적용
- 실패 비차단 (`run_kstartup` 패턴 — `subprocess` returncode 로깅, 파이프라인 계속)
- `run_pipeline.py`의 `run_bizinfo_enrich()`를 재사용/참조

### 2. GitHub Actions timeout 조정 (`daily-crawl.yml`)

- `crawl-bizinfo` step `timeout-minutes: 15` → enrich ~25분 추가 필요 → **40~45분으로 상향**
- job 전체 `timeout-minutes: 95` 여유 확인 (enrich 추가분 포함)

### 3. 검증

- `py run_all.py --mode bizinfo` 실행 → enrich 단계 로그 확인
- DB end_date 유지·증가 확인
- GHA `workflow_dispatch` 수동 트리거로 러너 환경 검증

---

## 주의

- GHA 러너는 빈 `db/biz.db`로 시작 (fresh crawl) — enrich가 러너에서 돌아야 운영 sync에 end_date 반영됨
- enrich HTTP fetch는 네트워크 안정 환경 전제 (절대 원칙 — 불안정 환경 본 실행 금지)

## 관련

- 14번째 정정: `docs/simulations/2026-05-20_phase3_poc_completed.md`
- 선행 백로그: `docs/backlog/enrich_persistence.md` (①)
- 핵심 코드: `run_all.py` (`run_bizinfo` L214 / `_post_merge_steps` L255), `.github/workflows/daily-crawl.yml`
