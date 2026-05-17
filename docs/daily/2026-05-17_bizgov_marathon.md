# 2026-05-17 BizGov 마라톤 17시간

> **별도 entry**: `docs/daily/2026-05-17.md` 는 b069 사이클 단일 단편. 본 entry 는 17시간 마라톤 종합.

## 작업 요약

- 시간: 09:00 ~ 26:00 (17시간 마라톤)
- push: **20 commit** (실측, `git log --since='2026-05-17' --until='2026-05-18 23:59'`)
- 처리 row: **~17,900 누적** (AI 통역 2,901 + AI 한줄요약 2,101 신규 + bizinfo dedup 12,884 삭제)
- 사고: 2건 (모두 fail-safe — sync flag reset 누락 + b066 cycle1 직렬 호출)
- 시뮬 entry: **4건 신규** (b066, b033, Phase 2, Phase 3)
- 비용: **~$2.90** (b066 $2.50 + b069 $0.10 + UI 작업 ~$0.30)

---

## 완료 작업 목록

### AI 친화 통역 + UI (b066 Phase 2-Alpha)

- `pipeline/ai_translate*.py` 모듈 + cache (commit `dc181fc`)
- batch (10건/요청) + chunked commit (50건) 패턴 도입 (`5b87ef0`)
- AI 친화 토글 UI — 원본 default + AI 강조 (`a53a24f`)
- 7 라우트 SQL SELECT 에 `ai_friendly_*` 보강 (`2e3e049`)
- 위젯 토글 (옵션 A → 옵션 3 통합) (`ab9354a`)
- 보라 배경 + ✨ AI 분석 뱃지 + 모드별 시각 효과 강화 (`f877cbb` b070)
- `sync_to_render.py` 에 `load_dotenv` 추가 (`b64e498`)
- **실측 coverage**: ai_friendly 2,901 / 4,510 (64.3%), widget 100%

### AI 한줄요약 (b069 Phase 2)

- `pipeline/ai_summary*.py` + `--widget-targets` flag 도입 (`d2b4def`)
- daily-crawl.yml 에 `ai-summary` step 추가 (`d2b4def` 와 함께)
- backfill (Step 7) + sync (Step 8) + 검증 (Step 9) + commits 5건 (Step 10) — 자율 진행
- 시뮬 entry → 백로그 → release → daily → LATEST 5 commit (`978a1f6 → d7045c1`)
- **실측 coverage**: ai_summary 2,914 / 4,510 (64.6%), widget 100% (2,901/2,901)
- 사후 발견: cache UPDATE 가 `synced_to_render` reset 안 함 → Phase 2.1 patch 백로그

### 자동화 (Actions)

- `daily-crawl.yml` 에 ai_translate step 추가 (`9521634` b067)
- `daily-crawl.yml` 에 ai_summary step 추가 (`d2b4def` b069)
- 5/18 06:00 KST cron 자동 작동 예정 — 일일 신규 ~50건/일 자동 처리
- 13:26~13:45 backfill cron 1,640건 자동 처리 실측 확인 (b069 step)

### 데이터 정제 (b033)

- bizinfo dedup — pblancId 기준 forward_merge (`fa7b48d`)
- 6 컬럼 보존 (`ai_friendly_title`, `ai_friendly_summary`, `ai_summary`, `ai_summary_at`, `description`, `attachments_json`)
- Dead reference cleanup (`click_log`, `favorite_projects`, `recommendations`)
- crawler 멱등성 fix (`canonical_url`)
- **실측 결과**: bizinfo 12,884 row 삭제, 2,862 row 보존 (총 84.2% 감소)
- DB 전체: 17,200 → 4,510 (-73.8%)

### 위젯 fix

- at_global 마감 가드 — `end_date < today` 차단 (`d8cb324`, `e50af25` b035)
- AT 위젯 사이트 동일 정렬 — 번호 DESC = 최신 공고 순 (`30b64fe` b068)
- 상세 페이지 추천 이유 변경 — 회사 정보 입력 link (`2706c1c`)
- 위젯 카드 회사정보 입력 유도 안내 (`ab9354a`)

### 시뮬 누적 시스템 정착

- 표준 템플릿 신설 (`c4942f7` b066 5/12~13 사고 회고 + 패턴 추출)
- entry 4건 신규 (b066, b033, Phase 2, Phase 3)
- 표준 템플릿 강화 — 보완 15~17 (사용자 가설 vs DB 실측 / 인프라 재사용 비율 / 단계 분할 임계점)
- INDEX 의 5/17 마라톤 학습 (공통 패턴 4건 + 사이클 1 차단 체크리스트 + 정확도 추세 표)
- **자본화 완료** — 미래 작업 사고 사전 차단 보장

---

## 사용자 가설 정정 (시뮬 가치)

| 사이클 | 사용자 가설 | 실측 | 오차 |
|---|---|---|---|
| b066 사이클 1 | 23분 | 7시간 | **18배** (직렬 호출 미반영) |
| b033 | 8,000 row 영향 | 12,884 row | **1.6배** |
| Phase 2 | 인프라 부재 가정 | 90% 존재 | **반대** (작업 0 → 작업 0.1) |
| Phase 3 | "확인 필요" 47% 해소 | 실측 0% 효과 | **반대** (선행 connector 확장 필수) |
| Phase 3 (사후) | 7 source 분산 가정 | **bizinfo 단일 99.87%** (사이트 캡처) | **반대** (작업 50%+ 감소) |

→ **사용자 가설 = 가설**. DB 실측 + 코드 grep + **사이트 캡처** 필수.

---

## 🔴 5/17 EOD 결정적 발견 — "확인 필요" 99.87% = bizinfo 단일

> **트리거**: 사용자가 위젯 "확인 필요" 카드의 실 분포를 사이트에서 직접 확인.

### 발견
- 확인 필요 2,126건 중 **99.87% (≈2,123건) = bizinfo(기업마당) 단일 source**
- Phase 3 시뮬 본문은 7 source 분산 가정 → **틀림**
- Phase 3.0 작업 단위가 7 site → **1 site (bizinfo)** 로 축소

### 함의
- Phase 3 합계 작업량: **6-8일 → 3-4일 (50%+ 감소)**
- "확인 필요" 해소 추정: 75% → 56% (단 작업량은 절반 이하)
- Phase 4 (target_company) 의존: 7 source attachment_text → **bizinfo 단일로 충분**
- W21 진입 가능: bizinfo PoC (4~6h) — 시연 회고 직후

### 권고 재정의 (LATEST 반영)
- W21: bizinfo connector PoC (4~6h) **← 변경 (기존: W22~W23 이월)**
- W22: Phase 3.1~3.5 본 구현 (3-4일)
- 나머지 6 source connector = 별도 backlog (영구 보류 가능)

---

## 핵심 통찰

### "사용자가 시스템을 이해하면 버그가 잡힌다"

- 사용자 메모 + DB 실측 + 코드 실측 = **3중 확인**
- 사용자 가설 절대 신뢰 X — 본 마라톤 4건 중 4건 가설 정정
- 사전 시뮬 분석으로 본 구현 시 시간 손실 차단:
  - Phase 2: 시뮬 30분 → 본 구현 1분 (인프라 재사용 발견)
  - Phase 3: 시뮬 1.5h → 본 구현 6~8일 → connector 확장 선행 발견 후 W22~W23 으로 이월

### "확인 필요" 정체 파악 (Phase 3 시뮬 부산물)

- 47% (~2,126건) = bizinfo crawler 마감일 수집 한계 (`end_date` NULL)
- 첨부 보유 0% — Phase 3 (첨부 분석) 만으로는 0% 효과
- Phase 3.0 (7 source connector 확장) 후 추정 75% 해소

### 시뮬 시스템의 ROI

- 시뮬 시간 비용: 1~2h × 4 entry = 6~8h
- 사고 사전 차단: Phase 3 본 구현 진입 시 6~8일 → 작업 0 (시뮬 단계 정정)
- **ROI**: ~20배 (사고 시간 vs 시뮬 시간)

---

## 다음 단계

| 일자 | 작업 | 모드 |
|---|---|---|
| 5/18 (오늘) | 카운트 카드 필터 (1.5h, DB 변경 0) + 응모서 모드 진입 | 응모서 freeze |
| 5/19 | 응모서 작성 (풀타임) | 응모서 freeze |
| 5/20 | **공모전 시연** | 응모서 freeze |
| 5/21~ (W21) | (선택) Phase 2.1 patch (sync flag reset 자동화) | 인프라 |
| W22~W23 | Phase 3.0 (bizinfo connector PoC, 4~6h) → 3.1~3.5 본 구현 | 신기능 |
| 7/3 | 본 응모 | — |

---

## push 리스트 (20건 — git log 실측)

```
f877cbb feat(b070): AI 요약 토글 효과 강화 - AI 결과물 모드별 노출
2706c1c fix: 상세 페이지 추천 이유에 회사 정보 입력 유도 추가
ab9354a feat(ui): 토글 'AI 요약 보기' + 위젯 카드 회사정보 입력 유도 안내
d7045c1 docs(LATEST): 진입점 갱신 — Phase 2 완료, Phase 2.1 patch 우선
4a2f801 docs(daily): 2026-05-17 — Phase 2 ai_summary 완비 + 시뮬 시스템 정착
a91f9ba docs(release): b069 Phase 2 ai_summary backfill + sync (2026-05-17 EOD)
e835f40 docs(b069): Phase 2 AI 한줄요약 백로그 — backfill + sync + Actions step
978a1f6 docs(simul-system): 시뮬 누적 시스템 정착 — Phase 2 entry + INDEX 신설
d2b4def feat(b069): Phase 2 — ai_summary batch + 자동화 + v1 master sync
fa7b48d feat(b033): bizinfo url 멱등성 (canonical_url) + dedup release package
30b64fe fix(b068): AT 위젯 정렬을 사이트 동일 (번호 DESC, 최신 공고 순)
9521634 feat(b067): Actions 에 ai_translate step 추가 — 5/18 신규 공고 자동 통역
2e3e049 fix(b066-ui-A): 7 라우트 SQL SELECT 에 ai_friendly_* 추가 (토글 작동)
a53a24f feat(b066-ui-A): AI 친화 통역 토글 버튼 — 원본 default + AI 강조 (5/20 시연)
b64e498 chore(b066): sync_to_render.py 에 load_dotenv 추가
5b87ef0 perf(b066 cycle2): batch prompt (10건/요청) + chunked commit (50건)
d8cb324 fix(b035): at_global 위젯 마감 공고 차단 (end_date 가드)
e50af25 fix(b035): at_global 위젯 SQL end_date 가드 추가 (마감 공고 제외)
dc181fc feat(b066 phase 2-alpha): AI 친화 통역 모듈 + ai_friendly_title/summary
c4942f7 docs(b066): 새 기능 영향 분석 표준 템플릿 신설 (5/12 사고 회고 + 5/13 패턴 추출)
```

---

## 본 entry 의 의미

- `docs/daily/2026-05-17.md` (b069 단편) + 본 entry (마라톤 종합) — 양쪽 보존
- 다음 세션 진입 시 본 entry 가 17시간 전체 컨텍스트 복원의 단일 source of truth
