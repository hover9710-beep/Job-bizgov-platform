# LATEST — BizGovPlanner 진입점

**마지막 갱신**: 2026-05-19 (Phase 3 통합 사전 시뮬 + 차별점 9가지)

---

## 5/17 EOD 상태 (최종)

### 시스템 안정성

- ✅ AI 친화 통역 100% widget coverage (2,901/2,901), 전체 64.3%
- ✅ AI 한줄요약 100% widget coverage (2,901/2,901), 전체 64.6%
- ✅ AI 친화 토글 (보라 + ✨ 뱃지)
- ✅ 자동화 (`daily-crawl.yml` ai_translate + ai_summary step)
- ✅ b033 dedup 84% 감소 (15,625 → 2,862)
- ✅ 운영 시스템 배너 (공식 API 1 + 자체 크롤러 7)
- ✅ 상세 페이지 데이터 출처 메타
- ✅ 필터 라벨 정확 명칭 (사후 발견 7)
- ✅ 모바일 가로 swipe 차단 (사후 발견 8, NEW)

### DB 현재 상태

| 항목 | 운영 | PC |
|---|---|---|
| 전체 | 4,617 | 4,510 |
| 접수중 | 335 | 71 |
| 마감 | 1,946 | — |
| 확인필요 | 2,336 | 2,126 |
| 마감임박 | 69 | — |

**확인필요 중 99.95% = bizinfo 단일 source** → Phase 3 작업 단위 4~6h 결정

### 응모서 차별점 9가지 (5/17 통합 + 5/19 통합 갱신)

1. **정확성 우선** — "확인 필요" ≈100% bizinfo (실측 99.95%), 사용자 가설 정정 6건
2. **누적 학습 워크플로우** — 시뮬 6건 영구 자산화
3. **AI 시대 솔로 워크플로우** — Claude Code 1인 운영
4. **시대적 정합성** — 이재명 5/15 X "창업중심 국가" 정확 매칭
5. **데이터 출처 신뢰성 + 자체 크롤러 운영** — 공식 API 1 + 자체 크롤러 7 (정기 운영)
6. **개발자 본인이 첫 사용자 + 운영 모니터링** — scratched my own itch
7. **다중 업종 솔로 사업가** ⭐ NEW — 1인 다도메인 통합 운영 (상세 보류)
8. **Phase 3 = 본문 AI 분석 시작점** ⭐ NEW — 메타 AI 100% → 본문 AI, BizGovPlanner AI 의 진짜 시작점
9. **Phase 4 = 회사 매칭 추천** ⭐ NEW — 본문 + target_company 매칭, 본문 기반 맞춤 추천

미래 10번째 (W22+):
- GoBizKorea API = 한국 중소기업 수출 도우미

---

## 5/18 작업 묶음 (응모서 모드 진입 전)

1. 🟨 cron 06:00 자동 작동 확인 (아침, 5분)
2. 🟨 사업자 등록 (홈택스, 10분) — 본인 명의
3. 🟨 카드 필터 클릭 가능 (1.5h, DB 변경 0)
4. 🟨 "확인 필요" tooltip (30분)
5. 🟨 메일 시스템 흐름 검증 (30분)

합계: 약 3시간

→ 응모서 모드 진입 = 5/18 오후

**Phase 3 진입 금지** — 시연 후 **W21 bizinfo PoC (4~6h)** → W22 본 구현 (3-4일).

---

## 5/18 ~ 7/3 일정

| 일자 | 작업 |
|---|---|
| 5/18 (월) | 작업 묶음 + 응모서 모드 진입 |
| 5/19 (화) | 응모서 본문 작성 + 시연 자료 |
| 5/20 (수) | **공모전 시연 (D-day)** |
| 5/21~ (W21) | Phase 3.0 bizinfo PoC (4~6h) |
| W22~W23 | Phase 3.1~3.5 본 구현 |
| W22+ | GoBizKorea / 신규 product 검토 |
| 6/11~ | Phase 4 (target_company) + 응모서 본 작성 |
| 7/3 | **본 응모 (JBTP)** |

---

## 5/17 사후 발견 8건 (모두 해결)

| # | 발견 | 해결 commit |
|---|---|---|
| 1 | 99.87% → 99.95% 실측 정확화 | (카피 갱신) |
| 2 | "실시간" + "06:00 갱신" 모순 → "정기 운영" | (카피 갱신) |
| 3 | source 명칭 (jbexport / at_global / jbtp_related) | a506a26 |
| 4 | 메일 시스템 흐름 (수신/모니터링/발송) | (백로그) |
| 5 | 자체 크롤러 운영 명시 강화 | (배너) |
| 6 | 7/3 응모서 시대적 정합성 (이재명 5/15 X) | (카피) |
| 7 | 필터 라벨 정정 (배너와 일치) | bfe4b52 |
| 8 | 모바일 가로 swipe 차단 | b19b144 |

## 5/19 통합 사전 시뮬 — Phase 3 AI 본문 분석 (사용자 가설 정정 누계 9건)

- `pipeline/file_text_extract.py` + `pipeline/attachment_text_pipeline.py` 이미 존재 (PDF + HWPX 추출 작동)
- DB 컬럼 4개 (`pdf_path`, `attachments_json`, `attachment_text`, `period_text`) 이미 schema 존재
- 그러나 **bizinfo 첨부 다운로드 0건** (99.95% 확인필요 단일 source)
- **인프라 재사용 35% → 50%+** (5/19 9번째 정정으로 ↑)
- Phase 3 작업량: 5~7일 → **3.5~5일** (5/19 9번째 정정)
- 5/17 사이클1 체크리스트 8/8 통과
- 시뮬 entry: `docs/simulations/2026-05-17_phase3_ai_integration.md`

### 🟢 5/19 22시 9번째 가설 정정 (사용자 사이트 캡처)

- 사용자 발견: bizinfo (기업마당) 는 첨부 파일 X (또는 거의 없음). "첨부서류" 자체가 본문으로 구성. 신청기간 본문에 명확 표시 (예: "신청기간: 2026.01.26 ~ 2026.12.31")
- CC 검증: `parse_bizinfo_dates` 이미 신청/사업/공고기간 라벨 지원, `period_text` 컬럼 활용 중 ✓
- **Phase 3.0 재정의**: bizinfo 첨부 다운로드 (4~6h) → bizinfo 본문 파싱 강화 (1~2h, **66% 감소**)

### 🟢 5/19 22시+ 10번째 가설 정정 (사용자 사이트 캡처 2건)

- 사용자 발견: bizinfo 본문도 기관별로 상이. "신청기간" 만 있고 "마감일" 별도 표기 X
- 증거:
  - **한국산업기술진흥원 KIAT** "산업부 혁신제품 지정기간 연장(1차) 공고" → 신청기간 2026.05.06 ~ 2026.06.05 → end_date = 2026-06-05
  - **한국세라믹기술원 KICET** → 신청기간 2026.04.06 ~ 2026.04.19 → end_date = 2026-04-19
- 공통 패턴: "신청기간" + ~ + 두 날짜 → 두 번째 날짜 = 실질 마감일
- **Phase 3.0 정밀 재정의** (시간 1~2h 유지):
  - 정규식 4종 (신청/접수/모집/공고기간 + 사업기간 보조 + 단일 마감일 fallback + AI fallback)
  - `end_date_confidence` 컬럼 (regex_strong / regex_weak / ai_high / ai_low / null)
  - DRY-RUN 30 row 매칭률 ≥80% 검증
  - `parse_bizinfo_dates` 호출 규약 = dict (string 직접 X) — 구현자 노트
- **메시지**: 기업마당도 BizGovPlanner 와 같은 고충 보유 → 한국 정부 지원사업의 본질적 문제 → BizGovPlanner 가 시스템적으로 해결

### 진행 시점

- **5/20 (D-day): 공모전 시연**
- **5/21 또는 5/22: Phase 3.0 PoC 진입** (시연 후 회복도에 따라)
- 사용자 가설 정정 누계: **10건**

---

## 컨텍스트 복원 명령 (다음 세션)

다음 세션 진입 시 순서:

1. **LATEST.md** (본 파일) — 진입점
2. **마라톤 종합 일지**: `docs/daily/2026-05-17_bizgov_marathon.md` — 20.5시간 전체 컨텍스트
3. **시뮬 INDEX**: `docs/simulations/INDEX.md` — 마라톤 학습 + 정확도 추세
4. **즉시 다음 작업**: 5/18 작업 묶음 1번 (cron 확인 → 사업자 등록 → 카드 필터)

```bash
# 빠른 컨텍스트 복원
cat docs/LATEST.md
cat docs/daily/2026-05-17_bizgov_marathon.md
cat docs/simulations/INDEX.md
```

새 채팅 진입:

```
@docs/LATEST.md 읽고 5/18 작업 시작
```

또는 GitHub raw fetch:
```
https://raw.githubusercontent.com/hover9710-beep/Job_bizgov_platform_dev/main/docs/LATEST.md
```

---

## 5/17 마라톤 핵심 통찰

> "사용자가 시스템을 이해하면 버그가 잡힌다"

- 5/17 사후 발견 8건 모두 사용자 직접 발견
- 시뮬 누적 시스템의 진짜 가치 = 사용자 본능화
- 7/3 응모서 핵심 차별점 = 누적 학습 워크플로우

### 사용자 가설 정정 (6건)

| 사이클 | 가설 | 실측 | 오차 |
|---|---|---|---|
| b066 사이클 1 | 23분 | 7시간 | 18배 |
| b033 | 8K row | 12.8K row | 1.6배 |
| Phase 2 | 인프라 부재 | 90% 존재 | 반대 |
| Phase 3 | 47% 해소 | 0% 효과 | 반대 |
| 데이터 출처 | 99.87% | 99.95% | 소폭 정확화 |
| 운영 표현 | 실시간 | 정기 | 모순 해소 |

→ **사용자 메모 + DB 실측 + 코드 실측 = 3중 확인 필수**

### 시뮬 ROI

- 시뮬 비용: 1~2h × 5 = 7~10h
- 사고 차단: Phase 3 본 구현 6~8일 사전 차단
- **ROI 20배+**

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
- AI 는 `git commit`/`git push` 자율 실행 X (본인 직접) — 단 사용자 명시 override 시 진행 OK
- 운영 DB 직접 변경 X (Render Shell 또는 정식 절차)
- ADMIN_KEY 채팅/로그/파일 노출 X
- 모드 A (인프라/사고) = v1 직접
- 모드 B (신기능) = v2 → release → cherry-pick

---

## 마라톤 최종 통계

| 항목 | 값 |
|---|---|
| 시간 | 20시간 30분+ |
| push | 19건+ |
| 처리 row | 19,000+ |
| 사고 | 2건 (모두 fail-safe) |
| 시뮬 entry | 5건 신규 |
| 사용자 가설 정정 | 6건 |
| 사후 발견 | 8건 (모두 해결) |
| 응모서 차별점 | 6가지 통합 + 99.95% 정확화 + 모바일 안정 |
| 비용 | 약 $2.94 |

---

## 관련 파일

- 마라톤 종합: `docs/daily/2026-05-17_bizgov_marathon.md`
- b069 단편: `docs/daily/2026-05-17.md`
- 5/14 사전: `docs/daily/2026-05-14.md` (Phase 2-A/B 완료)
- 시뮬 INDEX: `docs/simulations/INDEX.md`
- release 인덱스: `release/INDEX.md`
- 시뮬 template: `docs/templates/feature_impact_simulation.md`
- 7/3 응모서 카피: `docs/proposal/2026-07-03_jbtp_intro_copy.md`
- 데이터 출처 백로그: `docs/backlog/data_source_trust_display.md`
- 메일 검증 백로그: `docs/backlog/email_system_verification.md`
- source 매핑 백로그: `docs/backlog/source_org_name_mapping.md`
