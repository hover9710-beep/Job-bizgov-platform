# release/2026-05-12_b057_v2_cherrypick — 5/12 밤 b057 follow-up v2 sync

## 목적

v1 의 5/12 밤 2 commit 을 v2 로 cherry-pick. jbtp 사이트 url 파라미터 순서 변경 대응 + 누적 갱신 일지/백로그 follow-up.

대상 v1 commit:
- `0032f32` — `fix(b057): jbtp connector url 정규화 (사이트 파라미터 순서 변경 대응)`
- `06c02fe` — `docs(b057): 5/12 밤 daily + 057 Phase 2.1f follow-up (jbtp 누적 갱신)`

자세한 배경: `docs/daily/2026-05-12.md` "밤 추가" 섹션, `docs/backlog/057_jbtp_sync_diagnosis.md` Phase 2.1f follow-up.

## 파일

| 파일 | 내용 | v2 적용 가능 |
|---|---|---|
| `0001-fix-b057-jbtp-connector-url.patch` | `connectors/connector_jbtp.py` +14줄 (`_normalize_detail_url()`) | **수동 포팅 필요** — v2 connector_jbtp 가 4단계 분리 구조 (`parse`/`normalize` 분기) 라 v1 patch (단일파일 `parse_list_page`) 와 함수 위치 다름. 백로그 029 통째 sync 와 함께 적용 권장 |
| `0002-docs-b057-5-12-daily-057-Phase-2.1f-follow-up-jbtp.patch` | `docs/daily/2026-05-12.md` + `docs/backlog/057_jbtp_sync_diagnosis.md` | **직접 `git am` 가능** (apply 충돌 시 `--3way`) |

## v2 적용 명령

v2 working dir 에서:

```powershell
# 1) v2 main 최신화
git checkout main
git pull origin main

# 2) docs 패치 적용 (0002 만)
git am "<v1_path>\release\2026-05-12_b057_v2_cherrypick\0002-docs-b057-5-12-daily-057-Phase-2.1f-follow-up-jbtp.patch"

# 3) 충돌 시 3way 시도
# git am --abort
# git apply --3way "<path>\0002-*.patch"
# (수동 머지 후 git add + git am --continue)

# 4) 확인
git log --oneline -3
git show HEAD --stat

# 5) push (별도 승인 후)
# git push origin main
```

## 0001 (코드 패치) 수동 포팅 가이드

v2 `connectors/connector_jbtp.py` 의 표준 4단계 (`fetch` / `parse` / `normalize` / `save`) 중 `parse` 함수 (a[href] 추출 부분) 에 동일한 정규화 적용:

```python
_DATASID_RE = re.compile(r"dataSid=(\d+)")


def _normalize_detail_url(href: str) -> str:
    # 사이트가 2026-05 a[href] 파라미터 순서를 menuCd&boardId&dataSid 로 변경.
    # 옛 row(boardId&dataSid&menuCd) 와 url string 매칭 위해 옛 형식으로 통일 (idx_url UNIQUE 호환).
    m = _DATASID_RE.search(href or "")
    if not m:
        return urljoin(BASE, href)
    return (
        f"{BASE}/board/view.jbtp?"
        f"boardId=BBS_0000006&dataSid={m.group(1)}&menuCd=DOM_000000102001000000"
    )
```

→ `parse()` 내부의 `urljoin(BASE, href)` 또는 동등 호출 1줄을 `_normalize_detail_url(href)` 로 교체.

v2 가 이미 4단계 분리로 정리되어 있으므로, 본 fix 가 자연스럽게 백로그 029 통째 sync 진행 시 v1 → v2 통일에 반영될 가능성 있음. 별도 commit 으로 분리할지 029 와 묶을지는 사용자 결정.

## 의존성

- v2 가 commit `18d3556` (5/12 기준 main HEAD) 또는 그 이후일 것
- v2 docs/daily/2026-05-12.md 가 v1 와 동일한 (또는 양립 가능한) 상태여야 직접 `git am` 가능. 다르면 `--3way` 필요

## 검증

v2 적용 후:
1. `git log --oneline -3` — 새 commit 2개 확인 (또는 1개 — 0002 만 적용 시)
2. `git diff origin/main..HEAD` — v1 의 변경 분량과 일치 확인
3. push 전 `git status` 가 clean
4. push 후 GitHub PR 또는 main 직접 확인
