# source → 시스템/포털 정식명칭 매핑

**작성**: 2026-05-17 EOD 사후 발견 / **갱신**: 2026-05-17 진짜 최후 (정식명칭 확정)
**상태**: 1차 배너 + 2차 메타 반영 완료 / 잔여는 5/18 작업 묶음

---

## 최종 매핑 (5/17 EOD 정식명칭 — 시스템/포털 기준)

| source | 정식명칭 (display) | 비고 |
|---|---|---|
| bizinfo | 정부24 기업마당 | 공식 API |
| kstartup | K-Startup | 창업진흥원 운영 |
| jbtp | 전북테크노파크 | 약자 X, 정식명 |
| jbbi | 전북바이오융합원 | (구) 전북바이오융합산업진흥원 |
| jbexport | 전북경제통상진흥원 | (구) 전북수출 |
| at_global | aT수출통합지원시스템 | aT 소문자, 시스템명 |
| kseafood | 수산식품수출지원시스템 | 한국수산회 운영 |
| jbtp_related | 전북외테크노파크 | (구) JBTP 유관기관 |

---

## 정정 이력 (5/17 누적)

| source | 1차 (오전) | 2차 (사후 발견) | 3차 최종 (EOD) |
|---|---|---|---|
| jbexport | 전북수출 | 전북경제통상진흥원 | 전북경제통상진흥원 |
| at_global | AT | aT | aT수출통합지원시스템 |
| jbtp_related | JBTP 유관기관 | 전북외테크노파크 | 전북외테크노파크 |
| jbtp | JBTP / 전북테크노파크 (JBTP) | — | 전북테크노파크 |
| jbbi | JBBI / 전북바이오융합산업진흥원 (JBBI) | — | 전북바이오융합원 |
| kseafood | 한국수산회 | — | 수산식품수출지원시스템 |

---

## 영향 범위 (반영 완료 ✓ / 잔여 🟨)

- ✓ `templates/new.html` (1차 배너 chip)
- ✓ `templates/project_detail.html` (2차 상세 메타)
- ✓ `docs/proposal/2026-07-03_jbtp_intro_copy.md` (5번째 차별점)
- ✓ `docs/backlog/data_source_trust_display.md`
- 🟨 `templates/new.html` 의 **필터 라벨** (기관 필터 row, 라인 67~85)
  - "전북수출" / "JBTP유관" / "한국농수산식품유통공사(AT)" 등 그대로 — 5/18 작업
- 🟨 `pipeline/normalize_project.py` 의 라벨 사용 여부 확인 — 5/18
- DB 의 raw source 값은 그대로 (display name 만 변경)

---

## 진행 시점

- 5/18 작업 묶음 (카드 필터 + 신뢰성 배너 + 메타) 와 함께
- 또는 별도 5/19 짧은 사이클

---

## 검증

수정 후 확인:

- 위젯 카드 source 표시 확인
- 상세 페이지 source 표시 확인
- 필터 (있다면) 라벨 확인

---

## 관련

- 다층 노출 전략 본 문서: [data_source_trust_display.md](data_source_trust_display.md)
