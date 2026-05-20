# 백로그 ① — enrich 결과 영구화 (enrich_persistence)

> **신설**: 2026-05-20 (Phase 3.0 PoC 완료, 13번째 가설 정정)
> **우선순위**: 높음
> **예상 시간**: 2~4h
> **분류**: Phase 3 본 구현 핵심

---

## 문제

`--enrich-detail`로 채운 bizinfo `end_date`가 **매일 야간 파이프라인에 의해 wipe** 된다. PoC(5/20)에서 오전 enrich 513건이 같은 날 20:40 야간 크롤로 소멸.

### 2중 wipe 메커니즘

```
① JSON 덮어쓰기
   connectors/connector_bizinfo.py 기본 run() = 야간 20:37 크롤
   → data/bizinfo/json/bizinfo_all.json 전체 재생성 (end_date 없는 목록)
   → enrich 결과 JSON 소멸

② DB 덮어쓰기
   pipeline/update_db.py  _upsert_one() UPDATE 문 (L499-534)
   → end_date 컬럼에 보존 가드 없음 — 들어온 값으로 무조건 덮어씀
   → 야간 merge가 빈 end_date(새 크롤본)로 DB end_date 덮어씀
   ※ attachments_json·ai_summary·organization·notice_chk/order 에는
     "새 값 빈값이면 기존값 보존" 가드 있음 (5/12 사고 #1 대응). end_date만 없음.
```

→ Step 4로 DB 반영해도 다음 야간 파이프라인이 원위치시킴. **영구화 없이는 PoC 결과가 매일 소멸.**

---

## 영구화 방법 2가지

### 방법 A — 야간 파이프라인에 enrich 단계 통합 (권장)

`pipeline/run_pipeline.py` 흐름에 enrich 단계 삽입:

```
crawl(bizinfo) → enrich-detail → merge_jb → update_db
```

- `run_pipeline.py`의 `run_bizinfo()` 직후 `connector_bizinfo.py --enrich-detail` 자동 호출
- 매일 크롤 직후 enrich → merge → DB. JSON wipe 무관 (같은 사이클 내 소비)
- 장점: 근본 해결, 매일 최신 end_date 유지
- 비용: 야간 파이프라인 +25~30분 (HTTP fetch 1,400+건)

### 방법 B — update_db UPDATE 에 end_date 보존 가드 추가

`_upsert_one()` UPDATE 에 기존 가드 패턴 적용:

```
merged_ed = row["end_date"]
if not merged_ed and old_ed:   # 새 값 빈값이면 기존값 보존
    merged_ed = old_ed
```

- 장점: 코드 변경 최소 (5~10줄), 야간 파이프라인 시간 증가 없음
- 한계: 신규 공고는 여전히 enrich 안 됨 (별도 enrich 실행 필요). end_date wipe만 차단.

### 권장: A + B 병행

- B 먼저 (즉시 안전망, end_date wipe 차단)
- A 로 매일 자동 enrich (근본 해결)

---

## Phase 3 본 구현 진입 명세

1. 방법 B 적용 — `update_db.py` end_date 보존 가드 (사이클 분리: 단독 commit)
2. 방법 A 적용 — `run_pipeline.py` enrich 단계 통합
3. DRY-RUN — `--skip-bizinfo` 조합으로 wipe 미발생 검증
4. 백로그 ② (no_deadline_classification) 동반 적용 시 확인필요 추가 감소
5. 야간 파이프라인 1회 정상 작동 확인 (다음날 DB end_date 유지 검증)

---

## 검증 기준

- 야간 파이프라인 실행 후에도 DB bizinfo `end_date` 보유 수 유지 (감소 X)
- 확인 필요 건수 감소분 유지

## 관련

- PoC 회고: `docs/simulations/2026-05-20_phase3_poc_completed.md`
- 핵심 코드: `pipeline/update_db.py` (`_upsert_one` L376-534), `pipeline/run_pipeline.py`
- 백로그 ②: `docs/backlog/no_deadline_classification.md`
