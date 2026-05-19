# source → 공식 기관명 매핑 정정

**작성**: 2026-05-17 EOD 사후 발견
**상태**: 백로그 (5/18 작업 묶음 또는 5/19 짧은 사이클)

---

## 정정 필요 사항 (5/17 발견)

| source | 기존 표시 | 공식 정정 명칭 |
|---|---|---|
| jbexport | 전북수출 | 전북경제통상진흥원 |
| at_global | AT | aT (소문자) |
| jbtp_related | JBTP 유관기관 | 전북외테크노파크 |

---

## 영향 범위 (확인 필요)

- `templates/` 의 source 표시 위치 (위젯 카드 + 상세 페이지)
- `pipeline/normalize_project.py` (혹시 라벨 사용 시)
- 추천 알고리즘 어디서 사용? (Phase 3-4 통합 시점)
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
