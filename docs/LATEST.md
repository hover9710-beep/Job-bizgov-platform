# LATEST — 진입점 (다음 세션 컨텍스트 복원용)

**마지막 갱신**: 2026-05-17 진짜 EOD (17시간 마라톤 + 사이트 캡처 결정적 발견)

---

## 5/17 EOD 상태

### 시스템 안정성

- **AI 친화 통역**: 100% widget coverage (2,901/2,901), 전체 64.3%
- **AI 한줄요약**: 100% widget coverage (2,901/2,901), 전체 64.6%
- **AI 친화 토글**: 옵션 3 통합 작동 (위젯 + 상세 + 모드별 시각)
- **자동화**: `daily-crawl.yml` 의 ai_translate + ai_summary step 활성
- **dedup**: bizinfo 84.2% 노이즈 제거 (15,625 → 2,862)
- **DB 전체**: 17,200 → 4,510 (-73.8%)
- **운영 sync**: 5/17 EOD 시점 pending=0 (전 row 동기화)

### 5/18 ~ 5/20 모드 = 응모서 모드 (시스템 freeze)

| 일자 | 작업 |
|---|---|
| 5/18 (오늘) | 카운트 카드 필터 (1.5h, DB 변경 0) + 응모서 모드 진입 |
| 5/19 | 응모서 작성 (풀타임) |
| 5/20 | **공모전 시연** |

**Phase 3 진입 금지** — 시연 후 **W21 bizinfo PoC (4~6h)** → W22 본 구현 (3-4일).

### 🔴 5/17 EOD 결정적 발견 (사이트 캡처)

- 확인 필요 2,126건 중 **99.87% (≈2,123건) = bizinfo(기업마당) 단일 source**
- Phase 3.0 작업 단위: 7 site selector → **bizinfo 1 site (4~6h)**
- Phase 3 합계 작업량: **6-8일 → 3-4일 (50%+ 감소)**
- Phase 4 (target_company) 의존: bizinfo 단일 attachment_text 로 충분
- 사용자 가설 정정 5건 (마라톤 4건 + 본 사후 발견 1건)

### 시뮬 누적 시스템 (자본화 완료)

- 위치: `docs/simulations/`
- INDEX: `docs/simulations/INDEX.md` (5/17 마라톤 학습 + 사이클 1 차단 체크리스트 + 정확도 추세 표)
- entry 4건 누적:
  - `2026-05-17_phase2_ai_summary.md` (정식)
  - `2026-05-17_phase3_attachment.md` (사전, 사용자 가설 정정)
  - b066 / b033 회고 — backfill 권장 (W21 시간 여유 시)
- 표준 템플릿: `docs/templates/feature_impact_simulation.md` (보완 15~17 추가)
- **미래 작업 사고 사전 차단 보장 — 영구 자산화**

---

## 다음 작업 (우선순위)

1. 🟨 **5/18 06:00 cron 자동 작동 확인** (아침, 5분) — ai_translate + ai_summary step 정상 처리 확인
2. 🟨 **카운트 카드 필터** (1.5h, DB 변경 0)
3. 🟨 **응모서 작성** (5/18 ~ 5/19, 풀타임)
4. 🟨 **5/20 공모전 시연**
5. 🟦 W21+ **Phase 2.1 patch** — `ai_summary_cache.py` + `ai_translate_cache.py` 의 `synced_to_render = 0` 추가 (30분)
6. 🟦 **W21 Phase 3.0** (bizinfo connector PoC, 4~6h) → **W22 3.1~3.5 본 구현 (3-4일)** ← 사이트 캡처 발견으로 작업량 50%+ 감소, 진입 시점 W22→W21 당김
7. 🟦 **회고 entry backfill** — b066, b033 (W21 시간 여유 시)
8. 🟦 **7/3 본 응모** (6월 본격 시작) — 차별점: "단순 시스템 구축 ≠ 누적 학습 워크플로우"

---

## 컨텍스트 복원 명령 (다음 세션)

다음 세션 진입 시 순서:

1. **LATEST.md** (본 파일) — 진입점
2. **마라톤 종합 일지**: `docs/daily/2026-05-17_bizgov_marathon.md` — 17시간 전체 컨텍스트
3. **시뮬 INDEX**: `docs/simulations/INDEX.md` — 마라톤 학습 + 정확도 추세
4. **즉시 다음 작업**: 우선순위 1번 (5/18 cron 확인 → 카드 필터 → 응모서)

```bash
# 빠른 컨텍스트 복원
cat docs/LATEST.md
cat docs/daily/2026-05-17_bizgov_marathon.md
cat docs/simulations/INDEX.md
```

---

## 새 규칙 — 5/17 마라톤 학습 (사이클 1 차단)

신규 작업 진입 시 강제 검증. 하나라도 NO 면 진입 X:

- [ ] **DB 실측** 우선 (사용자 가설 vs 실측 표 작성)?
- [ ] **인프라 재사용 비율** 측정 (≥70% 면 안전)?
- [ ] **batch + chunked commit** 패턴 적용 (단건 직렬 호출 X)?
- [ ] **DRY-RUN + --limit 10** 사전 검증 단계?
- [ ] **단계 분할** (본 구현 >2일이면 필수)?
- [ ] **신규 backup** (DB 변경 시 사고 한도)?
- [ ] **운영 sync 정책 결정** (운영 enrich vs v1 master)?
- [ ] **회고 entry backfill** 계획 (사이클 종료 후)?

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

## 핵심 통찰 — 5/17 마라톤

### 사용자 가설 정정 (4건 중 4건)

| 사이클 | 가설 | 실측 | 오차 |
|---|---|---|---|
| b066 사이클 1 | 23분 | 7시간 | 18배 |
| b033 | 8K row | 12.8K row | 1.6배 |
| Phase 2 | 인프라 부재 | 90% 존재 | 반대 |
| Phase 3 | 47% 해소 | 0% 효과 | 반대 |

→ **사용자 메모 + DB 실측 + 코드 실측 = 3중 확인 필수**

### 시뮬 ROI

- 시뮬 비용: 1~2h × 4 = 6~8h
- 사고 차단: Phase 3 본 구현 6~8일 사전 차단
- **ROI 20배**

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

## 관련 파일

- 마라톤 종합: `docs/daily/2026-05-17_bizgov_marathon.md`
- b069 단편: `docs/daily/2026-05-17.md`
- 5/14 사전: `docs/daily/2026-05-14.md` (Phase 2-A/B 완료)
- 시뮬 INDEX: `docs/simulations/INDEX.md`
- release 인덱스: `release/INDEX.md`
- 시뮬 template: `docs/templates/feature_impact_simulation.md`
