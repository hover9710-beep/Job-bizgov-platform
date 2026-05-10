# 052. jbexport proxy 미작동 + 운영 DB sync 자동화

**상태**: 🔴 진행 중 (임시 우회 적용 / 본질 해결 다음 주)
**제안일**: 2026-05-10
**발견**: 5/10 위젯 사이트 66/65 누락 분석 — proxy down 5/8~ 부터 운영 DB 새 공고 누적 정지
**우선순위**: 높음 — 위젯 stale, 사용자 혼선

## 현상

5/10 백로그 049/050/051 운영 적용 후에도 위젯에서 사이트 66/65 누락:
- oder=1544 (사이트 66번): 운영 DB 미존재
- oder=1543 (사이트 65번): 운영 id=15365, title=`spSeq=93b55df14467448399e310540eab2e98` (백로그 035 detail 추출 실패 row)

v1 로컬 DB 에는 두 row 모두 정상 존재 (id=20283, 22915). 따라서 v1 로컬 daily run 은 정상 동작 중. 운영 DB 만 stale.

## 근본 원인

1. **proxy 미작동** (5/8~): 백로그 036 wrapper 가 4단계 (체크→자동시작→run_all→정리) 로 만들어졌지만, jbexport proxy 자체의 down 상태가 wrapper 외부 이슈. v1 로컬 daily 가 jbexport 만 우회로 수집 (또는 다른 경로) 중.
2. **운영 DB sync 자동화 부재**: v1 로컬 ↔ 운영 DB 사이에 자동 sync 메커니즘 없음. v2 의 코드는 push 로 배포되지만 DB row 는 운영이 자체 daily run 으로 채움. proxy 가 죽으면 운영 DB 가 멈춤.

= chain 사고. 둘 중 하나만 살아도 위젯 정상화. 현재 둘 다 죽은 상태.

## 임시 우회 (2026-05-10 적용)

`release/2026-05-10_jbexport_v1_sync/sync_two_rows.py` — v1 로컬 DB 의 정상 row 두 개 (id=20283, 22915) 를 운영 DB 에 hardcoded snapshot 으로 수동 sync. 단발성, 멱등.

기대 결과: 위젯 5건 = 사이트 66/65/64/63/62 정상 노출.

**주의**: 본 우회는 두 row 만 처리. proxy 가 계속 down 이면 매일 새 공고가 누락됨. 본질 해결 시급.

## 본질 해결 옵션

### A. proxy 를 Render service 로 띄우기
- 장점: 운영 환경 통일, v1 로컬 의존성 제거
- 단점: Render 추가 비용, 사이트 robots/rate-limit 정책 검토 필요
- 검토: Render free tier 에서 second service 가능 여부, 비용 영향

### B. 사이트 list API 직접 호출 (proxy 우회)
- 백로그 049 백필 스크립트가 이미 `JBEXPORT_LIST_URL` 직접 호출 패턴 검증 (`_fetch_one_year`, `_collect_all_rows`).
- 장점: proxy 불필요, 코드 단순화
- 단점: 사이트 측에서 직접 호출 차단 가능성 (User-Agent / IP / 쿠키 워밍 필요)
- 검증 완료: 049 백필 1회 실행 시 200건 정상 수집됨 → **잠재 가능성 높음**
- 추가 작업: detail 페이지 (백로그 035) 도 같은 패턴 검증 필요

### C. v1 로컬 daily run → 운영 DB 자동 push
- 매일 v1 로컬 run_all 후 운영 DB 로 변경분 push (sqlite diff 또는 row-by-row UPSERT)
- 장점: 임시 우회의 자동화 버전, proxy 위치 변경 불필요
- 단점: v1 PC 가 항상 켜져있어야 함, 네트워크 의존, Render DB 직접 접근 권한 필요 (현재 Render Shell 만 가능)

### D. Render scheduler 에서 jbexport daily run
- Render Cron Job 으로 `run_all jbexport` 직접 실행
- 장점: 가장 깔끔한 운영 환경 일원화
- 단점: proxy 미작동 시 동일 문제 (B 와 결합 필요)
- B+D 결합이 가장 강력: Render Cron + 사이트 직접 호출

## 다음 주 진행 우선순위

1. **B 검증** (proxy 우회 list+detail 직접 호출): 1~2일
   - 049 백필 패턴을 daily run 으로 확장 (list + detail meta)
   - 사이트 차단 여부 모니터링 (1주일 trial)
2. **B 통과 시 → D 적용** (Render Cron): 0.5일
   - 기존 v1 local cron 을 Render Cron 으로 이전
3. **B 실패 시 → A 검토** (Render proxy service): 2~3일
   - 비용/정책 검토 후 의사결정
4. C 는 fallback 옵션 — A/B/D 모두 막힌 경우만

## v1+v2 cherry-pick

본 백로그 명세는 v2 → v1 cherry-pick 대상 (코드 변경 없음, 명세만):
- v2: `docs/backlog/052_proxy_sync_resolution.md`
- v1: 같은 경로 동일 사본

## 관련 자료

- 백로그 035: jbexport detail 추출 실패 → 본 사고의 표면 증상 (broken row title=spSeq=...)
- 백로그 036: bizplnner wrapper proxy 자동 시작 — wrapper 자체는 정상, proxy down 은 외부 이슈
- 백로그 049: notice_order 백필 — 사이트 list API 직접 호출 패턴 검증 완료
- release/2026-05-10_jbexport_v1_sync/: 본 사고의 임시 우회

## 임시 우회 후속 처리

본 백로그 본질 해결 (B+D 또는 A) 완료 후:
- `release/2026-05-10_jbexport_v1_sync/` archive
- 운영 DB 의 sync 된 두 row 가 daily run 결과와 충돌하지 않는지 1주일 모니터링
