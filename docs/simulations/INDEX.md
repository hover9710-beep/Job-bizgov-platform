# 시뮬 누적 시스템 INDEX

> **목적** — 새 기능 진입 전 영향 분석 (`docs/templates/feature_impact_simulation.md`) 을 시간순으로 누적, 시뮬 정확도 학습.
> **정착**: 2026-05-17 — Phase 2 ai_summary 사이클부터 정식 누적 시작.

---

## 누적 entry

| 일자 | 백로그 | 대상 | 분류 | 결과 |
|---|---|---|---|---|
| 2026-05-17 | b069 (Phase 2) | [AI 한줄요약 `ai_summary` 완비](2026-05-17_phase2_ai_summary.md) | backfill + 자동화 | 결정 대기 |
| 2026-05-17 | Phase 3 (사전 1차) | [첨부 추출 + end_date 자동](2026-05-17_phase3_attachment.md) | 영향 분석 | 가설 정정 — 7 source connector 확장 선행 필수, W22~W23 권장 |
| 2026-05-17 | Phase 3 (통합 갱신) | [기존 첨부 인프라 재사용 + AI 본문 분석](2026-05-17_phase3_ai_integration.md) | 영향 분석 2차 | 가설 6번째 정정 — 인프라 35% 재사용 / bizinfo connector + AI 신규 / 5~7일 단계 6분할 / 사이클1 체크리스트 8/8 |
| 2026-05-19 | Phase 3.0 (PoC 사전) | [PoC 사전 정밀 시뮬 — 11번째 가설 정정](2026-05-19_phase3_poc_pre_simulation.md) | 영향 분석 3차 | description 컬럼 본문 X (날짜) / `--enrich-detail` 이미 존재 → Phase 3.0 코드 변경 0, 1.5~3h |
| 2026-05-20 | Phase 3.0 (PoC 완료) | [PoC 완료 회고 — 13번째 가설 정정](2026-05-20_phase3_poc_completed.md) | 실행 회고 (8번째 entry) | 확인필요 2,302→1,446 (−37%) / 파싱 정확성 100% / enrich 비영구 (야간 wipe) → Phase 3 본 구현 = "영구화" |

### 회고 미작성 (시뮬 사후 entry — 시간 여유 시 backfill)

| 일자 | 백로그 | 대상 | 비고 |
|---|---|---|---|
| 2026-05-17 | b066 (Phase 2-Alpha) | AI 친화 통역 (`ai_friendly_title/summary`) | 5/17 본격 사이클 — 회고로 entry 작성 권장 |
| 2026-05-17 | b033 | bizinfo dedup (canonical_url) | 5/17 release 사이클 — release/INDEX.md 와 교차 참조 |

---

## 시뮬 정확도 추세

| 항목 | b066 (5/17) | b033 (5/17) | Phase 2 (5/17) | Phase 3 (5/17, 사전) |
|---|---|---|---|---|
| 시간 추정 정확도 | 85% | — | 36% 빠름 | TBD |
| 사고 발견 정확도 | 70% | — | 가설 D | TBD |
| 비용 추정 정확도 | 95% | — | 99% | TBD |
| 영향 row 정확도 | — | 60% | 100% (2,090/2,091) | **사용자 가설 정정** (47% → 0% 즉시) |

→ 누적 entry 가 늘수록 본 표 갱신. 패턴 학습으로 정확도 향상 추적.

### Phase 3 학습 포인트

- **사용자 가설을 그대로 받지 말고 DB 실측 우선** — "47% 해소" 가설 → 실측 0% 발견
- 다단계 작업 (3.0 connector 확장 → 3.1 다운로드 → 3.2 추출 → 3.3 AI → 3.4 DB → 3.5 UI) 의 의존성 분석
- 인프라 재사용 비율 추정 (5/17 b066/b033/b069 패턴 → 80%)

---

## 🧠 5/17 마라톤 학습 — 공통 패턴 (4 entry 추출)

### 발견 1: 사용자 메모 정확도 평균 50~70%
- b033: 사용자 명세 8K → 실측 12.8K (1.6배)
- Phase 3: 사용자 가설 47% 해소 → 실측 0% 효과
- b066: release package 존재 가정 → 실측 부재
- Phase 2: 인프라 부재 가정 → 실측 90% 존재

**→ 사용자 가설은 가설일 뿐. DB 실측 + grep 필수.**

### 발견 2: 시간 추정 오차 평균 2~5배 (사이클 1 패턴)
- b066 사이클 1: 23분 → 7시간 (18배 빗나감, 직렬 호출)
- b066 사이클 2: 27분 → 17.3분 (-36%, batch 패턴)
- Phase 2: 추정 1.5h → 실 17분 (batch 재사용)

**→ batch + chunked commit 패턴 강제. 직렬 호출 X.**

### 발견 3: 인프라 재사용 비율 평균 70~80%
- Phase 2: 90% (ai_summary 모듈 + cache + daily-crawl step)
- Phase 3: 80% 추정 (batch 패턴, schema, sync)

**→ 신규 인프라 최소화. 5/17 검증 패턴 재사용.**

### 발견 4: 단계 분할 필수 (>2일 작업)
- Phase 3: 6-8일 → 5단계 분할 (3.0~3.5)
- b066: 사이클 1+2+3+4+5 분할 (각 0.5~2시간)

**→ 큰 작업은 단계별 사이클 + 회고 entry 각각.**

---

## ✅ 사이클 1 패턴 차단 체크리스트

> 신규 작업 진입 시 강제 검증. 하나라도 NO 면 진입 X.

- [ ] **DB 실측** 우선 (사용자 가설 vs 실측 표 작성)?
- [ ] **인프라 재사용 비율** 측정 (≥70% 면 안전)?
- [ ] **batch + chunked commit** 패턴 적용 (단건 직렬 호출 X)?
- [ ] **DRY-RUN + --limit 10** 사전 검증 단계?
- [ ] **단계 분할** (본 구현 >2일이면 필수)?
- [ ] **신규 backup** (DB 변경 시 사고 한도)?
- [ ] **운영 sync 정책 결정** (운영 enrich vs v1 master)?
- [ ] **회고 entry backfill** 계획 (사이클 종료 후)?

---

## 📈 시뮬 정확도 추세 (entry 별)

| 항목 | b066 | b033 | Phase 2 | Phase 3 (사전) |
|---|---|---|---|---|
| 사용자 메모 정확도 | release 부재 정정 | 1.6배 차이 정정 | 인프라 90% 발견 | 가설 0% 정정 |
| 시간 추정 정확도 | 사이클 1: 18x 빗남 → 사이클 2: 36% 빠름 | TBD (회고 미작성) | 36% 빠름 | TBD |
| 비용 추정 정확도 | 95% | TBD | 99% | TBD |
| 영향 row 정확도 | — | 60% | 100% | 사용자 가설 정정 |
| 인프라 재사용 비율 | (신규) | (신규) | 90% | 80% |

**패턴 추출**:
- 시간 추정은 batch 패턴 적용 시 0.5~0.8배 (빠르게 끝남)
- 사용자 메모 정확도 평균 ~60%
- 비용 추정 정확도 가장 높음 (~95%+)
- 인프라 재사용 비율 ≥80% 면 사고 위험 낮음

---

## 🎯 다음 시뮬 entry 에 반영할 학습

1. **사용자 가설 비판적 검증** — 가설 그대로 받지 말고 DB 실측 + grep 우선
2. **재사용 비율 측정** — 신규 인프라 최소화, 5/17 패턴 활용
3. **단계 분할 명세** — >2일 작업은 단계별 사이클 + 회고 entry
4. **batch + chunked commit 강제** — 직렬 호출 사고 차단
5. **회고 entry backfill 정착** — 사이클 종료 직후 또는 1주 내

---

## 사용 패턴

### 새 기능 진입 시

1. `docs/templates/feature_impact_simulation.md` 의 9 단계 + 5 보완 적용
2. 본 INDEX 의 선행 entry 의 "회고" 섹션 참조 → 비슷한 작업 정확도 / 함정 학습
3. 신규 entry 를 `docs/simulations/YYYY-MM-DD_<백로그>_<대상>.md` 로 저장
4. 본 INDEX 에 1 줄 추가
5. 진행 후 entry 의 회고 섹션 채움

### 명명 규칙

- 파일명: `YYYY-MM-DD_<백로그번호 또는 키워드>.md`
- 예: `2026-05-17_phase2_ai_summary.md`, `2026-05-18_b070_attachment_extract.md`

---

## 관련 문서

- 영향 분석 템플릿: [`docs/templates/feature_impact_simulation.md`](../templates/feature_impact_simulation.md)
- 백로그 INDEX: `docs/backlog/`
- release log: `release/INDEX.md`
- daily 일지: `docs/daily/YYYY-MM-DD.md`

---

## 변경 이력

| 일자 | 변경 | 작성 |
|---|---|---|
| 2026-05-17 | 신설 — Phase 2 ai_summary entry 첫 누적, 시스템 정착 | CC |
| 2026-05-17 | Phase 3 entry 추가 — 사용자 가설 (47% 해소) 정정 (실측 0%), 7 source connector 확장 선행 명시 | CC |
| 2026-05-17 | Phase 3 통합 갱신 entry — 기존 첨부 인프라 정밀 조사 (jbexport 60 .bin / pypdf+HWPX 추출 모듈 / DB 컬럼 4개 존재), 인프라 35% 재사용, 5~7일 단계 6분할, 차별점 8/9 (Phase 3 본문 AI + Phase 4 회사 매칭) | CC |
| 2026-05-19 | 9번째 가설 정정 (bizinfo 본문이 첨부서류 역할) — Phase 3.0 작업량 4~6h → 1~2h (66% 단축), 합계 3.5~5일 | CC |
| 2026-05-19 | 10번째 가설 정정 (기관별 본문 상이, "신청기간" 만 / "마감일" 별도 X, 사이트 캡처 2건) — Phase 3.0 정규식 4종 + AI fallback + `end_date_confidence` 컬럼 정밀화, 시간 1~2h 유지 | CC |
| 2026-05-19 | 11번째 가설 정정 (PoC 사전 시뮬) — `description` 컬럼 = 날짜 문자열 (본문 X) / 본문 DB 부재 / `connector_bizinfo.py` 에 `fetch_detail()` + `--enrich-detail` + `_extract_period_status_from_detail_table()` 이미 존재 → Phase 3.0 = 기존 스크립트 실행 (코드 0), 7번째 entry 신설 | CC |
| 2026-05-20 | 13번째 가설 정정 (enrich 비영구성) + PoC 검증 — 확인필요 2,302→1,446 (−37%), 파싱 정확성 100%, 야간 wipe 발견 → Phase 3 본 구현 = 영구화, 백로그 ①② 신설, 8번째 entry 신설 | CC |
| 2026-05-21 | 14번째 가설 정정 (①A 오배치) — enrich 자동화를 `run_pipeline.py`(수동 웹 버튼)에 넣어 야간 경로(`run_all.py`) 미반영. ②·①B는 `update_db.py` 경유로 운영 반영. `enrich_in_run_all.md` 백로그 신설 | CC |
| 2026-05-21 | 14번째 정정 해소 — enrich 단계를 `run_all.py` `run_bizinfo()`에 통합 (commit `db5f6bb`), `run_all.py --mode bizinfo` 검증 통과. Phase 3 본 구현 ①② 완료 | CC |
