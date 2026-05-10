# 057. jbtp 운영 DB 5/2~5/7 신규 누적 안된 원인 진단

**상태**: 🟢 신규 (다음 주 진단)
**제안일**: 2026-05-10
**발견**: 5/10 백로그 053 follow-up #2 — Render IP 차단 우회 sync 실행 시뮬에서 운영 113 ↔ v2 128 (15건 차이) 발견
**우선순위**: 높음 — 052 와 동일 chain 사고 가능성, 운영 데이터 stale 위험
**연관**: 052 (jbexport proxy/sync 자동화), 029 (v1/v2 connector divergence)

## 알려진 사실

### v2 vs 운영 차이
- **v2 로컬 DB jbtp**: 128 row (053 백필 ground-truth, 사이트 9페이지 동기)
- **운영 DB jbtp** (Render): 113 row (053 sync 실행 전 시점)
- **차이**: 15 row = 5/4~5/7 사이트 신규 등록 분 (시뮬 검증)
  - notice_order DESC 상위 15 url 이 운영 DB 미존재
  - 시뮬: v1 DB 사본에서 최신 15 url 삭제 → 113 row stale 재현 → sync_jbtp_v1_to_render.py UPSERT → 128 row 복구 PASS

### v1 로컬 vs 운영 차이
- v1 로컬 DB jbtp = 128 row (5/10 053 백필 후 v2 와 동일 상태로 가정 — sync 직전 시뮬 데이터)
- 즉 **v1 로컬에는 신규 row 가 들어왔지만, 운영에는 누적되지 않음** (5/2~5/7 6일간)

## 가설

### H1 — jbtp 운영 sync 메커니즘 자체가 미작동
- 운영 DB 가 v1 로컬 DB 의 변경분을 자동으로 받아오는 메커니즘이 없을 가능성
- 백로그 052 와 동일 패턴 (jbexport 도 같은 chain) → **공통 sync 자동화 부재**

### H2 — Render daily run 이 jbtp 만 실패
- 운영 측 daily 가 jbtp 사이트 fetch 시 IP 차단 (053 follow-up #2 에서 확인) → 매 daily 실패
- 다른 source (bizinfo / kstartup / 등) 는 정상 누적되는데 jbtp 만 stale 인지 확인 필요

### H3 — proxy down (5/8~) 와는 시기 불일치
- jbexport 052 는 proxy 5/8~ down 이 원인. 그러나 jbtp 는 5/2~5/7 (proxy down 이전) 부터 stale.
- jbtp 는 proxy 무관 (HTML 직접 호출, 053 진단에서 확인) → proxy 문제 아닌 다른 원인

## 확인 필요 사항

### 1) 운영 DB sync 메커니즘 식별
- Render Cron Job 등록 현황 (jbtp 별도 cron 이 있는지)
- v1 로컬 daily run 이 운영 DB 에 push 하는 경로 (있는지 / 없는지)
- 자동 commit / 자동 deploy hook 흐름 추적
- 결과: **sync 메커니즘 = (없음 / Render Cron / v1→운영 push / 기타)** 확정

### 2) 5/2~5/7 그 메커니즘이 왜 멈췄는지
- **(없음)**: 그렇다면 v1 로컬은 어떻게 5/10 시점 128 row 인지 (백로그 053 백필이 사이트에서 직접 받음 — 운영 stale 의 본질 원인 = sync 자동화 부재)
- **(Render Cron)**: cron 로그 확인, jbtp daily 실패 로그
- **(v1→운영 push)**: v1 cron / scheduler 로그, 5/2~5/7 동안 push 가 발생했는지

### 3) 다른 source 동시 점검
- bizinfo (10,684), kstartup (400), jbbi (362), jbexport (65~68), at_global, kseafood
- 운영 DB 의 각 source 별 최신 row created_at 확인 → 5/2~5/7 동안 누적된 source / 정지된 source 분리
- 결과: jbtp 만 정지 (H2) vs 모든 source 정지 (H1) 판별

## 해결 방향 (가설별)

### H1 인 경우 (sync 자동화 부재)
- 백로그 052 와 통합 — 공통 해결책 필요 (B+D / A)
- 임시 sync 스크립트 (053 의 sync_jbtp_v1_to_render.py 패턴) 매주 수동 실행 (단기)
- 본격: 사이트 list API 직접 호출 + Render Cron (사이트 차단 시 한국 IP proxy 필요)

### H2 인 경우 (Render IP 차단 jbtp 만)
- jbtp 만 별도 우회 — sync 스크립트 정기 실행 (053 패턴) 또는 한국 IP proxy
- 다른 source 는 기존 메커니즘 유지

### H3 (현재 우세) 인 경우 (proxy 무관 + jbtp 만 정지)
- **시기 (5/2~5/7) 와 jbtp 정지의 인과 관계 추적**
- v1/v2 release 이력 확인 — 5/2 이전에 jbtp 코드 수정 / connector 변경 / DB 스키마 변경
- 백로그 030 (connector 표준화 Phase 2 v2) 가 5/7 완주 → 그 시점 v2 jbtp connector 변경 영향 가능

## 진행 절차

### Phase 1 — 사실 수집 (자율, ~30min)
- 운영 DB 각 source 최신 row created_at 확인 (Render Shell SQL)
- v1 로컬 DB 각 source 최신 row created_at 확인 (로컬 SQL)
- 두 결과 비교 → 어떤 source 가 stale 인지 분포 확정

### Phase 2 — sync 메커니즘 식별 (자율 + 사용자)
- Render Dashboard cron jobs 확인 (사용자가 캡처)
- v1 schedule / scheduler 설정 확인
- 사용자 인터뷰: "운영 DB 가 어떻게 업데이트되는지" 멘탈 모델 확인

### Phase 3 — 가설 확정 + 해결 (사용자 stop)
H1 / H2 / H3 중 어느 것인지 확정하고 해결 방향 합의.

### Phase 4 — 해결 적용 (별도 작업)
- 임시: 053 sync 스크립트 1주일 / 매일 실행 모니터링
- 본격: 052 와 통합 또는 별도 백로그 분리

## 관련 자료

- 백로그 052: jbexport proxy/sync 자동화 (동일 chain 가능성 — 같은 본질)
- 백로그 029: v1/v2 connector divergence (5/10 시점 jbtp connector 가 v1=legacy, v2=4단계 분리 — 영향 가능성)
- 백로그 030: connector 표준화 Phase 2 v2 (5/7 jbtp 4단계 분리 완주)
- 백로그 053: jbtp 위젯 fix + Render IP 차단 우회 sync (본 백로그의 표면 증상 진단)
- release/2026-05-10_jbtp_widget_fix/sync_jbtp_v1_to_render.py: 임시 우회 (단발성, 본 백로그 본격 해결 까지 매주 모니터링)

## 메모

- 본 백로그 진단 결과에 따라 052 와 통합될 수도, 분리될 수도 있음
- 만약 H1 (sync 자동화 부재) 으로 확정되면 052 + 057 = 동일 본질 → 한 백로그로 합치고 057 close
- 5/2~5/7 동안 운영 측 daily 가 어떻게 동작했는지 확인이 핵심 — Render Dashboard / cron logs 가 1차 자료
