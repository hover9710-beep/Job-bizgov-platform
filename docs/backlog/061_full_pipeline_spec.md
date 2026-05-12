# 061. 전체 파이프라인 명세 (사이트 → fetch → merge → DB → sync → widget)

**상태**: 🟢 신규 (W20 진입 전 선행 필수)
**제안일**: 2026-05-12
**발견 계기**: 5/12 위젯 미반영 사고. `merge_jb.py` 의 `notice_order`/`notice_chk` drop 이 6일간 잠재 → 5/11 사이트 신규 공고 등록 시 노출. 단편 fix (백로그 049/051) 가 merge 파이프라인까지 추적 안 한 결과.
**우선순위**: **HIGH** — 058 / 059 / 057 Phase 2.4+ 진행 전 필수
**연관**: 049 (jbexport notice_order 도입), 051 (위젯 정렬), 057 (sync 정책), 062 (E2E 테스트), 063 (derivative cache)

## 목적

사이트 응답에서 위젯 노출까지의 **단방향 데이터 흐름** 을 명세화. 각 단계가 어느 컬럼/필드를 어떻게 채우는지 단일 source-of-truth 로 고정. 신규 컬럼/필드 추가 시 영향 범위 체크리스트로 사용.

## 단계 정의 (jbexport 기준)

| # | 단계 | 입력 | 출력 | 책임 |
|---|---|---|---|---|
| 1 | 사이트 upstream API | `getWork1Search.do` POST | JSON `{data: [{oder, js_title, SP_SEQ, CODE_KR, STS_TXT, ...}]}` | (사이트) |
| 2 | proxy forward | upstream JSON | 동일 JSON + `_proxy_debug` | `connectors/connectors_jbexport/jbexport_proxy.py:api_jbexport_list` |
| 3 | connector fetch | proxy 응답 | `data/jbexport/YYYY-MM-DD.json` (한국어 키 + 영문 키 혼합) | `pipeline/jbexport_daily.py:fetch_all_announcements` → `extract_announcement` |
| 4 | new 후보 추출 | today.json vs yesterday.json | `data/jbexport_new.json` | `pipeline/jbexport_daily.py:run_daily` |
| 5 | merge | 모든 source `data/**/*.json` | `data/all_jb/all_jb.json` (영문 키 통일) | `pipeline/merge_jb.py:merge_jb_json` |
| 6 | DB upsert | `all_jb.json` | `db/biz.db` `biz_projects` row | `pipeline/update_db.py:_upsert_one` |
| 7 | 운영 sync | v1 `biz_projects` (synced=0) | Render `/var/data/biz.db` row | `pipeline/sync_to_render.py` → `appy.py:/api/sync` |
| 8 | 위젯 표시 | 운영 `biz_projects` | HTML | `appy.py` 위젯 라우트 |

## 컬럼별 채움 경로 (jbexport notice_order 예시)

| 단계 | `notice_order` 값 | 키 이름 |
|---|---|---|
| 1 사이트 | `1545` | `oder` (소문자) |
| 2 proxy forward | `1545` | `oder` 보존 |
| 3 connector | `1545` | `notice_order` (영문) — `extract_announcement` 가 `row.get("oder")` 추출 |
| 4 new 후보 | `1545` | `notice_order` 보존 |
| 5 merge | `1545` | `notice_order` 보존 — `_normalize_item`/`_normalize_jb_new_item` 의 return dict 에 명시적 패스스루 필요 |
| 6 DB upsert | `1545` | `notice_order` INTEGER 컬럼 |
| 7 운영 sync | `1545` | `notice_order` (sync_to_render.py `_COLUMNS` 에 포함) |
| 8 위젯 | `ORDER BY notice_order DESC` 정렬키 | |

> 5/12 사고는 단계 5 의 `notice_order` 패스스루 누락. 단계 1~4 정상, 5 에서 drop, 단계 6+ 는 None → 0 으로 받음.

## 신규 컬럼 추가 시 체크리스트

신규 컬럼 (예: `notice_chk`, `notice_create_dt`, `synced_to_render`, …) 추가 시 아래 8단계 모두 검토:

- [ ] 1. 사이트 응답에 키 존재 (또는 default 값 정책)
- [ ] 2. proxy 가 키 보존 (변형/축약하지 않음)
- [ ] 3. connector `extract_*` 가 추출 + 영문 키로 mapping
- [ ] 4. today.json / new.json 에 보존
- [ ] 5. `_normalize_item` + `_normalize_jb_new_item` return dict 에 명시적 추가
- [ ] 6. `update_db._prepare_row` row dict + INSERT/UPDATE SQL 에 추가 + merge 로직 검토 (049 패턴: 새 값이 비었으면 old 유지)
- [ ] 7. `sync_to_render._COLUMNS` 에 추가 + 운영 `/api/sync` 의 UPSERT 컬럼 일치
- [ ] 8. 위젯 / API 응답에서 사용 여부

## 다른 source 의 명세 (개략)

| source | fetch 단계 | merge 매핑 | 비고 |
|---|---|---|---|
| jbtp | `pipeline/jbtp_*.py` | `_normalize_item` (file_source=jbtp) | seq 컬럼 = 정렬키 |
| bizinfo | `connectors/connector_bizinfo*` | `_normalize_bizinfo_row` | 별도 normalize 함수 |
| kstartup | `connectors/connector_kstartup.py` | `_normalize_item` (file_source=kstartup) | |
| jbbi / at_global / kseafood | 각 connector | `_normalize_item` 통과 | 위젯 후순위 (jbbi/kseafood) |

각 source 의 정렬키 / unique 키 / sync 대상 여부는 057 Phase 2.2/2.3 명세 참조.

## 산출물

1. 본 문서 자체 — 명세 단일 source-of-truth
2. 신규 백로그 작성 시 본 체크리스트 참조 (template 로 활용)
3. `pipeline/` 디렉토리 README 또는 module docstring 에 본 문서 링크 (W20+ 작업)

## 결정 필요 (사용자)

- 본 명세를 `pipeline/PIPELINE.md` 또는 별도 ARCHITECTURE 문서로 승격 여부
- 각 단계 책임자 (= module owner) 표시 정책

## 다음 액션

1. 본 문서 review + 다른 source 단계별 매핑 완전화 (현재 jbexport 기준만 상세)
2. 백로그 062 의 E2E 테스트가 본 명세를 검증 fixture 로 사용
