# 2026-05-10 jbexport 운영 DB 수동 sync (백로그 052 임시 우회)

## 배경
jbexport proxy 미작동(2026-05-08~) → run_all 의 jbexport 수집 실패 → 운영 DB 새 공고 누적 정지. 5/10 위젯에서:
- 사이트 66번 (notice_order=1544): 운영 DB 미존재
- 사이트 65번 (notice_order=1543): 운영 id=15365 옛 broken row (title=`spSeq=93b55df14467448399e310540eab2e98`, 백로그 035 detail 추출 실패 패턴)

## 본질 해결 ≠ 본 release
근본 원인 = proxy down + 운영 DB sync 자동화 부재. 본질 해결은 **백로그 052** 별도 진행 (다음 주). 이 release 는 단발성 수동 우회.

## 변경 사항
- `release/2026-05-10_jbexport_v1_sync/sync_two_rows.py` (신규)
  - v1 로컬 DB 의 정상 row 두 개를 hardcoded snapshot 으로 보유
  - 운영 DB 자동 백업 (sha256 + ts 라벨 `052_v1_sync`)
  - `_ensure_columns` — 049/050 미적용 환경 자동 보완
  - `_cleanup_broken_rows` — 같은 spSeq 보유 broken row (title=`spSeq=...`) 가 다른 url 로 존재하면 삭제 (UNIQUE 충돌 회피)
  - `ON CONFLICT(url)` UPSERT — url 일치 시 id 유지 + 모든 필드 갱신, url 신규 시 INSERT
  - 멱등성: 이미 정확한 데이터면 unchanged 통계 0
  - 사이트 영향: 0 (HTTP 호출 없음)

## 데이터 출처
v1 로컬 DB (`C:\Users\custo\OneDrive\바탕 화면\커서앱통합_v1\db\biz.db`) 에서 추출 (2026-05-10):
- id=20283: spSeq=eb876dda1c7949f3b10e0e29685b5b43, oder=1544, status=진행
- id=22915: spSeq=93b55df14467448399e310540eab2e98, oder=1543, status=마감

## 검증 (DRY_RUN)
**v2 로컬 (jbexport 65건, 두 url 미존재)**:
```
inserted: 2, updated: 0, unchanged: 0
```

**v1 로컬 (jbexport 정상 + 두 url 존재)**:
```
inserted: 0, updated: 0, unchanged: 2  ← 멱등성 PASS
위젯 상위 5: oder=1544, 1543, 1542, 1541, 1540
```

**운영 DB 예상**:
```
cleanup_deleted: 0  (spSeq=93b55... 옛 row 의 url 이 정상 url 과 같다고 가정 시)
inserted: 1  (spSeq=eb876..., oder=1544)
updated: 1  (spSeq=93b55..., id=15365 유지, title/dates/oder 정상화)
위젯 상위 5: oder=1544, 1543, 1542, 1541, 1540 (사이트 66/65/64/63/62 일치)
```

## 실행 (Render Shell)
```bash
# preview
DRY_RUN=1 python release/2026-05-10_jbexport_v1_sync/sync_two_rows.py
# apply
python release/2026-05-10_jbexport_v1_sync/sync_two_rows.py
```

## 적용 범위
- v2 (개발): 본 release 만
- v1 (운영 cherry-pick 대상): 같은 파일 release/ 경로에 배치 (코드 수정 X)
- 운영 DB: Render Shell 에서 1회 실행

## 후속 작업
- **백로그 052** (`docs/backlog/052_proxy_sync_resolution.md`) 진행 (다음 주)
- 본 release 는 백로그 052 본질 해결 후 archive 후보
