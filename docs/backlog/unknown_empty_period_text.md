# 백로그 — 확인필요 833건 period_text 부재 진단 (unknown_empty_period_text)

> **신설**: 2026-05-21 (위젯/무마감 분류 작업 중 발견)
> **우선순위**: 중
> **예상 시간**: 진단 30분~1h
> **선행**: `docs/backlog/no_deadline_classification.md` (②), `docs/backlog/enrich_persistence.md` (①)
> **상태**: ✅ **완료 (2026-05-21)** — 진단 + fix(DB 기반 re-enrich) 모두 완료

---

## 문제

DB 실측 (5/21): `status='확인 필요'` **905건 중 833건 (92%)이 `period_text` 빈값**.

- 무마감 키워드 분류(②)는 period_text 의 키워드에 의존 → period_text 자체가 없으면 무력
- 키워드별 분포: 수시 1 / 연중 0 / 추후 9 / 상이 50 — 키워드로 줄일 행 거의 없음
- → 확인필요를 더 줄이려면 **period_text 가 왜 833건이나 비었는지** 진단이 본질

`period_text` 는 `--enrich-detail` 이 상세 페이지에서 신청기간 라벨을 추출해 채운다.
빈값 = enrich 미적용 / enrich 가 신청기간 라벨을 못 찾음 / 애초에 상세에 기간 표기 없음.

---

## 진단 결과 (2026-05-21)

DB 분석 + 상세 페이지 8건 샘플 fetch:

| 항목 | 결과 |
|---|---|
| 대상 | 833건 (확인필요 + period_text 빈값) |
| source | bizinfo 832 / kstartup 1 |
| url 보유 | 832 / 833 |
| collected_at | 2026-04 **722건 (87%)** / 2026-05 111건 |
| 현재 크롤본 대조 | **829건이 `bizinfo_all.json`에 없음** (과거 누적분) / 있음 2 |
| 상세 페이지 샘플 8건 | **8/8 fetch 성공, 8/8 신청기간 존재** → end_date 추출 가능 (2026.05.03~05.15) |

**결론:**
1. 833건은 사실상 전부 bizinfo 과거 누적분 — 829건이 현재 크롤 리스트에서 빠짐.
2. ①A enrich 자동화는 `bizinfo_all.json`(현재 크롤본)만 처리 → **이 829건엔 영영 안 닿음**.
3. 그러나 상세 페이지엔 신청기간이 그대로 존재 (샘플 8/8) — "마감일 부재 정상 공고"가 아니라 **"enrich 가능한데 한 번도 안 된 행"**.
4. 4월 수집분이라 샘플 8건 모두 end_date가 5월 초·중순 = 현재 마감 → enrich 시 대부분 `'확인 필요'→'마감'`으로 정정.

→ **오분류 확정.** 확인필요 906건 중 ~829건이 "이미 마감됐으나 enrich 누락으로 확인필요에 남은" stale 행.

---

## 해결 방향 (다음 사이클 — fix)

`--enrich-detail`은 JSON(`bizinfo_all.json`) 기반이라 크롤본 밖 829행에 못 닿음.
**DB 기반 일회성 re-enrich** 필요:

- `status='확인 필요' AND period_text 빈값 AND source='bizinfo' AND url 보유` 행을 DB에서 직접 조회
- 각 url 로 `fetch_detail()` → `period_text`/`start_date`/`end_date`/`status` UPDATE (`update_db` upsert 로직 재사용 권장)
- 멱등 (재실행 안전), DB 백업 선행, ~829건 HTTP (~15분, 안정 네트워크)
- 예상 효과: 확인필요 906 → **~80** (대부분 `'마감'`으로 정정)
- 구현: 신규 스크립트 또는 connector 에 `--enrich-db` 플래그 (코드 변경, 모드 A)

---

## ✅ fix 완료 (2026-05-21)

신규 스크립트 `pipeline/enrich_db_bizinfo.py` — DB 기반 re-enrich:

- 대상 **831건 전수 처리, fetch 실패 0**
- 산출 status: 마감 792 / 접수중 25 / 확인필요 14
- **확인 필요 906 → 89 (−817, −90%)** (bizinfo 확인필요 → 88)
- 잔여(확인필요 + period_text 빈값) **1건** — 상세에 신청기간 자체가 없는 정당한 케이스
- 멱등 (재실행 안전). DB 백업 `db/biz.backup.20260521_072002_pre_enrich_db.db`
- 과거 누적 행이라 야간 `update_db` 가 재처리 안 함 → 결과 durable

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
