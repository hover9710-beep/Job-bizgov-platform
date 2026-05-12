# 063. derivative cache 정책 — raw 우선순위 + cache cleanup

**상태**: 🟢 신규 (W20+)
**제안일**: 2026-05-12
**발견 계기**: 5/12 위젯 미반영 사고. `merge_jb.py` 가 `data/**/*.json` 전수 스캔 후 dedup 캐시 `seen_keys` 가 first-come-wins. derivative 파일 (`data/history/`, `data/merged/`, `data/filtered/`, `data/all_jb.json`) 이 `notice_order=None` 상태로 raw 보다 먼저 캐시 진입 → raw row dropped.
**우선순위**: MEDIUM — 본 사고의 보조 원인. fix 패치 3 (dedup 보강) 으로 1차 완화 완료. 정책 수준 정리는 후속.
**연관**: 061 (파이프라인 명세), 062 (E2E 테스트), `pipeline/merge_jb.py:collect_json_files`

## 문제 정의

`pipeline/merge_jb.py:collect_json_files()` 가 `DATA_DIR.rglob("*.json")` 으로 모든 json 을 source 로 본다. 단순 알파벳 sort. 그러나 그 안에는:

| 카테고리 | 예시 경로 | 성격 |
|---|---|---|
| **raw** | `data/jbexport/2026-05-12.json`, `data/jbexport_new.json`, `data/bizinfo/json/bizinfo_all.json`, `data/kstartup/kstartup_all.json` | connector 직접 출력 |
| **derivative** | `data/history/all_sites_*.json`, `data/merged/all_sites.json`, `data/merged/new.json`, `data/filtered/recommended.json`, `data/all_jb.json` (self-copy) | 다른 단계의 후처리 결과 |
| skip 대상 | `data/all_jb/all_jb.json` (OUT_PATH, 제외됨), `today.json`/`yesterday.json` (제외됨) | |

문제: derivative 파일은 컬럼 일부가 stripped 또는 stale. raw 와 같은 spSeq/title 을 가진 row 가 derivative 에 먼저 매칭되면 raw 가 dedup 으로 dropped.

## 5/12 사고 재구성

1. `data/history/all_sites_2026-05-12.json` (collect 순서상 jbexport raw 보다 빠름) 에 24225/24226 spSeq 존재 + `notice_order=None`
2. merge_jb 가 history 의 row 를 먼저 채택 (`seen_keys.add(key)`)
3. 이후 `data/jbexport/2026-05-12.json` 의 같은 row (notice_order=1546) 도착 → key 매칭 → `duplicates_removed += 1; continue` → drop
4. `all_jb.json` 의 최종 row 는 history 출처 (notice_order=None)
5. update_db → DB 의 notice_order=0

## 현 완화 (fix 패치 3, 5/12 적용)

`merge_jb_json` dedup loop 에 보강 로직 추가:
```python
if key in seen_keys:
    existing = merged[seen_index[key]]
    for fk in ("notice_order", "notice_chk"):
        if not existing.get(fk) and item.get(fk):
            existing[fk] = item[fk]
    ...
```
→ derivative 가 먼저 들어와도 raw 가 나중에 도착하면 빈 필드 채움. 1차 안전망.

## 본격 정책 (본 백로그)

### A. raw 우선순위 정렬

`collect_json_files()` 의 sort key 변경:
```python
def priority(path):
    norm = str(path).replace("\\","/")
    if "/jbexport/" in norm or norm.endswith("jbexport_new.json"): return (0, str(path))
    if "/bizinfo/" in norm: return (0, str(path))
    if "/kstartup/" in norm: return (0, str(path))
    # raw 0, derivative 1
    return (1, str(path))
files.sort(key=priority)
```
→ raw 가 먼저 dedup 캐시에 들어가 first-come-wins 자체 적용.

### B. derivative 디렉토리 source 에서 제외

`data/history/`, `data/merged/`, `data/filtered/`, `data/all_jb.json` (root self-copy) 를 source 에서 명시적 제외:
```python
if OUT_DIR in p.parents: continue
if p.name in ("today.json", "yesterday.json"): continue
# 추가
if any(part in p.parts for part in ("history", "merged", "filtered")): continue
if p == DATA_DIR / "all_jb.json": continue
```
→ 더 명확. derivative 가 다시 source 가 되는 self-loop 차단.

### C. raw 마커 파일 정책

raw connector 출력에 `_source_type: "raw"` 메타데이터 추가 → merge_jb 가 raw 만 채택.
- 장점: 명시적
- 단점: 모든 connector 수정 필요 (범위 큼)

### 추천: **A + B 조합** — sort 우선순위 + derivative 디렉토리 명시 제외. C 는 장기.

## 영향 범위 검토

- `data/history/`, `data/merged/`, `data/filtered/` 가 다른 모듈에서 출력되는 정합 데이터인지 확인 필요 (단순 cache 인지, downstream 의존 있는지)
- `pipeline/filter_recommend.py` 등 derivative 출력 모듈의 입력 경로 / 신선도 정책 점검

## 추가 cleanup 정책

- `data/history/` 보관 기간 (현재 일별 누적 = 무한 누적)
- `data/all_jb.json` (root) 의 의미 (왜 OUT_PATH 외에 root 에도 복사하는가) — `merge_jb_json` line 345-350. 호환 의도면 OK, 아니면 제거 검토.

## 산출물

1. `merge_jb.py` collect/sort 패치 (A + B)
2. derivative 디렉토리 cleanup cron (선택)
3. CLAUDE.md 또는 PIPELINE.md 에 "raw 우선순위" 정책 명시

## 결정 필요 (사용자)

- A + B 즉시 적용 여부 (다른 source 영향 가능성 검토 후)
- derivative 디렉토리 보관 정책 (history/ 무한 vs N일)

## 다음 액션

1. 백로그 061 + 062 선행
2. 본 백로그 착수 시 A + B 패치 + E2E (062 시나리오 4) 로 회귀 검증
