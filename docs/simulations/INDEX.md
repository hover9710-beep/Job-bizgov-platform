# 시뮬 누적 시스템 INDEX

> **목적** — 새 기능 진입 전 영향 분석 (`docs/templates/feature_impact_simulation.md`) 을 시간순으로 누적, 시뮬 정확도 학습.
> **정착**: 2026-05-17 — Phase 2 ai_summary 사이클부터 정식 누적 시작.

---

## 누적 entry

| 일자 | 백로그 | 대상 | 분류 | 결과 |
|---|---|---|---|---|
| 2026-05-17 | b069 (Phase 2) | [AI 한줄요약 `ai_summary` 완비](2026-05-17_phase2_ai_summary.md) | backfill + 자동화 | 결정 대기 |

### 회고 미작성 (시뮬 사후 entry — 시간 여유 시 backfill)

| 일자 | 백로그 | 대상 | 비고 |
|---|---|---|---|
| 2026-05-17 | b066 (Phase 2-Alpha) | AI 친화 통역 (`ai_friendly_title/summary`) | 5/17 본격 사이클 — 회고로 entry 작성 권장 |
| 2026-05-17 | b033 | bizinfo dedup (canonical_url) | 5/17 release 사이클 — release/INDEX.md 와 교차 참조 |

---

## 시뮬 정확도 추세

| 항목 | b066 (5/17) | b033 (5/17) | Phase 2 (5/17, 진행 전) |
|---|---|---|---|
| 시간 추정 정확도 | 85% | — | TBD |
| 사고 발견 정확도 | 70% | — | TBD |
| 비용 추정 정확도 | 95% | — | TBD |
| 영향 row 정확도 | — | 60% | TBD |

→ 누적 entry 가 늘수록 본 표 갱신. 패턴 학습으로 정확도 향상 추적.

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
