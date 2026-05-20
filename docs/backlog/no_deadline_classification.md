# 백로그 ② — 무마감 공고 status 재분류 (no_deadline_classification)

> **신설**: 2026-05-20 (Phase 3.0 PoC 완료)
> **우선순위**: 중
> **예상 시간**: 30분~1h
> **분류**: product 정확도 개선

---

## 문제

Phase 3.0 PoC 재실행에서 fetch된 1,474건 중 **711건(48.1%)이 마감일 없는 공고**. 이들은 `신청기간` 필드가 날짜가 아니라 키워드 텍스트:

| 키워드 | 의미 |
|---|---|
| 예산 소진시까지 | 예산 소진 전까지 상시 접수 |
| 선착순 접수 | 선착순 마감 |
| 상시 접수 | 연중 상시 |
| 모집 완료시 | 정원 충족 시 마감 |
| 세부사업별 상이 / 차수별 상이 | 하위 공고별 별도 |

이들은 **마감일 부재가 정상 상태**인데, `pipeline/normalize_project.py`의 `infer_status`가 end_date 없음만 보고 `'확인 필요'`로 남김 → **오분류**.

---

## 영향

- PoC 후 DB bizinfo 확인 필요 1,446건 중 상당수가 이 무마감 공고
- `infer_status`가 키워드를 인식해 `'상시'`(또는 `'접수중'`)로 분류하면 **확인 필요 추가 ~600건+ 감소** 전망
- bizinfo 확인 필요 비율: 47.6% → 30% 미만 가능

---

## 해결 명세

`infer_status(period_text, start_date, end_date, today)` 에 키워드 패턴 분기 추가:

```
무마감 키워드 = ["예산 소진", "선착순", "상시", "모집 완료", "별 상이", "차수별"]
if end_date 없음 and period_text 에 무마감 키워드 포함:
    return "상시"   (또는 start_date 가 과거면 "접수중")
```

- 신규 status 값 `'상시'` 도입 여부 결정 필요 (UI 필터·위젯 영향 검토)
- 또는 기존 `'접수중'`으로 흡수 (start_date 과거 + 무마감 → 접수중)
- `update_db.py` `_prepare_row` / `_backfill_infer_status` 양쪽 경로 적용

---

## 검증 기준

- 무마감 키워드 행이 `'확인 필요'`에서 빠지는지 확인
- 확인 필요 건수 추가 감소분 측정 (목표 ~600건+)
- 정상 마감일 공고의 status 가 영향받지 않는지 회귀 확인

## 관련

- PoC 회고: `docs/simulations/2026-05-20_phase3_poc_completed.md`
- 핵심 코드: `pipeline/normalize_project.py` (`infer_status`), `pipeline/update_db.py`
- 백로그 ①: `docs/backlog/enrich_persistence.md` (동반 적용 권장)
