# 062. E2E 파이프라인 테스트 자동화

**상태**: 🟢 신규 (W20)
**제안일**: 2026-05-12
**발견 계기**: 5/12 위젯 미반영 사고. 단편 fix 검증이 단일 단계 (예: today.json) 까지만 이뤄져 merge 단계 drop 을 못 잡음. 신규 INSERT 가 운빨로 5/11 까지 없었기에 잠재.
**우선순위**: **HIGH** — 061 명세 작성 후 즉시 착수
**연관**: 061 (파이프라인 명세 — 본 테스트의 검증 fixture), 057 Phase 2 (sync 정상성)

## 목적

`run_pipeline.py` 또는 daily run 종료 직전에 **사이트 → 위젯 정렬 가능 상태** 까지의 핵심 invariant 를 자동 검증. 단편 fix 가 다른 단계를 break 시키는 사고를 즉시 감지.

## 검증 시나리오 (jbexport 기준)

### 시나리오 1 — 신규 INSERT 의 정렬키 정상성

신규로 들어온 row (예: `created_at > now - 1d`) 의 핵심 컬럼이 정상값인지:

```python
# pseudo
new_rows = SELECT * FROM biz_projects WHERE source='jbexport' AND created_at > date('now', '-1 day')
for row in new_rows:
    assert row.notice_order > 0, f"notice_order=0 for new row id={row.id} title={row.title}"
    assert row.title and row.url, ...
```

5/12 사고 시나리오 — `notice_order=0` 인 신규 row 가 2건 → assert fail → 알림.

### 시나리오 2 — 사이트 ↔ DB 정합

사이트 API 최상위 N건의 spSeq 가 v1 DB 의 `source='jbexport' AND status='진행'` 상위 N건과 일치:

```python
site_top = upstream_api(length=10).data
db_top = SELECT url FROM biz_projects WHERE source='jbexport' AND status='진행' ORDER BY notice_order DESC LIMIT 10

assert {sp for sp in site_top[:5]} == {extract_sp(url) for url in db_top[:5]}, "위젯 상위 5건 불일치"
```

### 시나리오 3 — sync 무결성

`synced_to_render=1` row 의 운영 DB 존재 + 핵심 컬럼 동기:

```python
# 샘플 N건 운영 DB 와 비교 (Render Shell or /api/diff 엔드포인트)
```

### 시나리오 4 — derivative 파일 보강 검증

`merge_jb_json` 의 dedup 보강 로직이 동작하는지:
- `data/history/` 또는 `data/merged/` 에 raw 보다 먼저 들어간 row 가 있을 때, 최종 `all_jb.json` 에 `notice_order` 가 채워져 있어야.

## 구현 방안 후보

### A. `run_pipeline.py` 끝에 검증 step
- `pipeline/validate_e2e.py` 신규
- daily run 끝에 호출, 실패 시 비zero exit + kakao/mail 알림
- 장점: 자동화, 즉시 감지
- 단점: daily 실행 지연 (사이트 API 추가 호출 필요)

### B. 별도 cron (sites_vs_db.py 확장)
- 이미 `scripts/debug/jbexport_site_vs_db_diff.py` 존재
- 통합/확장 후 별도 schedule
- 장점: daily 부하 분리
- 단점: 실시간성 ↓

### C. pytest 기반 unit + integration
- `tests/test_pipeline_e2e.py`
- v1 daily run 후 또는 CI 에서 실행
- 장점: 표준 패턴
- 단점: 사이트 의존 = flaky 가능성

추천: **A + C 조합** — daily 끝에 A 의 핵심 invariant (시나리오 1, 4) + CI 에서 C 의 mock fixture (시나리오 2, 3 sample) 로 분리.

## 알람 조건 / 임계

| 시나리오 | 임계 | 행동 |
|---|---|---|
| 1 notice_order=0 신규 row | ≥ 1건 | 즉시 mail/kakao + daily fail |
| 2 사이트↔DB 상위 5 불일치 | ≥ 1건 | 즉시 알림 |
| 3 sync 무결성 샘플 mismatch | ≥ 1건 | 즉시 알림 |
| 4 dedup 보강 누락 | ≥ 1건 | warning 로그 (daily 통과) |

## 산출물

1. `pipeline/validate_e2e.py` (시나리오 1, 4)
2. `tests/test_pipeline_e2e.py` (시나리오 2, 3 mock)
3. `auto_run.bat` 마지막 step 에 `validate_e2e.py` 추가
4. fail 시 알림 hook (기존 mail/kakao 코드 재사용)

## 결정 필요 (사용자)

- 알람 채널 (mail / kakao / Slack)
- 실패 시 daily run 중단 여부 (즉시 stop vs 계속 + 보고)

## 다음 액션

1. 백로그 061 명세 완성 후 본 백로그 착수
2. 시나리오 1 + 4 가 최소 MVP — 5/12 사고 재발 방지가 1차 목표
