# 백로그 — 확인필요 833건 period_text 부재 진단 (unknown_empty_period_text)

> **신설**: 2026-05-21 (위젯/무마감 분류 작업 중 발견)
> **우선순위**: 중
> **예상 시간**: 진단 30분~1h
> **선행**: `docs/backlog/no_deadline_classification.md` (②), `docs/backlog/enrich_persistence.md` (①)

---

## 문제

DB 실측 (5/21): `status='확인 필요'` **905건 중 833건 (92%)이 `period_text` 빈값**.

- 무마감 키워드 분류(②)는 period_text 의 키워드에 의존 → period_text 자체가 없으면 무력
- 키워드별 분포: 수시 1 / 연중 0 / 추후 9 / 상이 50 — 키워드로 줄일 행 거의 없음
- → 확인필요를 더 줄이려면 **period_text 가 왜 833건이나 비었는지** 진단이 본질

`period_text` 는 `--enrich-detail` 이 상세 페이지에서 신청기간 라벨을 추출해 채운다.
빈값 = enrich 미적용 / enrich 가 신청기간 라벨을 못 찾음 / 애초에 상세에 기간 표기 없음.

---

## 진단 명세

833건(`status='확인 필요' AND (period_text IS NULL OR TRIM(period_text)='')`)을 분류:

1. **source 분포** — bizinfo vs 그 외. bizinfo 외라면 enrich 대상 자체가 아님
2. **start_date / end_date 유무** — 날짜가 아예 없는지
3. **url 유무** — url 없으면 enrich 불가
4. **collected_at 연식** — enrich 자동화(①A, 5/21) 이전 누적분인지
5. **샘플 상세 페이지 확인** — 실제로 신청기간 라벨이 없는 공고인지 (정당한 '확인 필요')

→ 분류 결과로 대응 결정:
- enrich 미적용 누적분 → 일괄 재enrich
- 상세에 기간 표기 자체가 없는 공고 → 정당한 '확인 필요' (오분류 아님)
- url 부재 → 별도 처리

---

## 참고

- ①A enrich 자동화(`run_all.py` 통합)로 **신규 공고는 매일 보강**됨 — 본 백로그는 기존 누적 833건 한정
- 무마감 키워드 분류 한계: `docs/backlog/no_deadline_classification.md`
- 핵심 코드: `connectors/connector_bizinfo.py` (`--enrich-detail`), `pipeline/normalize_project.py` (`infer_status`)
