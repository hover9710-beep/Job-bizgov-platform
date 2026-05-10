# -*- coding: utf-8 -*-
"""백로그 053 follow-up: v2 백필 ground-truth → 운영 DB UPSERT sync (Render IP 차단 우회).

배경:
  053 백필 (backfill_jbtp.py) 가 사이트 9페이지 fetch 로 122 row 를 백필.
  v2 로컬 DB 에선 PASS. 운영 (Render Shell) 실행 시 ConnectTimeout —
  jbtp.or.kr 가 Render 해외 IP 차단 추정. 사이트 fetch 자체가 운영에서 막힘.

  추가 발견 (2026-05-10): 운영 DB 가 5/2~5/7 stale 로 113건 (v2 128건 - 15건).
  최신 사이트 row (seq 2198~2193 등) 가 운영 DB 미존재 → UPDATE only sync 로
  는 누락. UPSERT 확장 필요.

본 스크립트 = 단발성 우회 (UPSERT 확장판). v2 로컬 DB (053 백필 apply 완료)
의 jbtp 128 row full snapshot 를 운영 DB 에 url 기준 UPSERT.

대상:
  - 운영 미존재 url → INSERT (snapshot 의 모든 컬럼 사용, 052 sync_two_rows 패턴)
  - 운영 존재 url → UPDATE (3 필드만 — notice_chk, notice_order, start_date)
    049 merge 보호: 새 값 0/'' + 옛 값 비-0/비-'' → 옛 값 보존

정책:
  - 멱등성: 같은 값이면 UPDATE 0. 두 번 실행해도 안전.
  - 사이트 영향: 0 (HTTP 호출 없음, JSON snapshot 사용).
  - 운영 row 의 다른 모든 필드 (title/organization/ai_summary/...) 는 UPDATE 시
    그대로 보존 → 백로그 029 (v1/v2 connector divergence) 영향 0.

실행 (Render Shell):
  DRY_RUN=1 python release/2026-05-10_jbtp_widget_fix/sync_jbtp_v1_to_render.py  # preview
  python release/2026-05-10_jbtp_widget_fix/sync_jbtp_v1_to_render.py            # apply

흐름:
  1) DB 자동 탐색 → SHA256 + 타임스탬프 백업 (DRY_RUN 시 생략)
  2) 컬럼 자동 보장 (notice_chk + notice_order + notice_create_dt ALTER, idempotent)
  3) JSON snapshot (v1_jbtp_dump.json) 로드 → {url: full_row_dict}
  4) DB jbtp row 순회 → url 매칭 → 3 필드 UPDATE (merge 보호)
  5) snapshot_only url → INSERT (full row)
  6) 결과 요약 (matched / updated / unchanged / inserted / snapshot_only_skip / no_match)
     + 위젯 시뮬
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


_HERE = Path(__file__).resolve()
_ROOT = _HERE.parent.parent.parent
_DUMP = _HERE.parent / "v1_jbtp_dump.json"


# INSERT 시 사용할 컬럼 (id/created_at/updated_at/view_count 제외 — DB 자체 관리)
INSERTABLE_COLS = (
    "url",
    "title",
    "organization",
    "source",
    "site",
    "start_date",
    "end_date",
    "status",
    "description",
    "collected_at",
    "ministry",
    "executing_agency",
    "receipt_start",
    "receipt_end",
    "biz_start",
    "biz_end",
    "raw_status",
    "attachments_json",
    "period_text",
    "ai_summary",
    "ai_summary_at",
    "recommend_label",
    "recommend_label_at",
    "attachment_text",
    "score",
    "reason",
    "apply_url",
    "notice_create_dt",
    "notice_chk",
    "notice_order",
)


def _resolve_db_path() -> Path:
    env = (os.getenv("DB_PATH") or "").strip()
    if env:
        return Path(env)
    candidates = [
        Path.cwd() / "db" / "biz.db",
        _ROOT / "db" / "biz.db",
    ]
    for p in candidates:
        if p.exists():
            return p
    return Path.cwd() / "db" / "biz.db"


def _backup_db(db_path: Path) -> Path:
    if not db_path.exists():
        raise FileNotFoundError(f"DB 파일 없음: {db_path}")
    h = hashlib.sha256()
    with open(db_path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    digest = h.hexdigest()[:12]
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = db_path.with_name(f"biz.db.backup_{ts}_053_jbtp_v1sync_{digest}")
    shutil.copy2(db_path, backup_path)
    print(f"[sync] DB 백업: {backup_path.name} (sha256={digest})", flush=True)
    return backup_path


def _ensure_columns(conn: sqlite3.Connection) -> None:
    cols = {str(c[1]) for c in conn.execute("PRAGMA table_info(biz_projects)").fetchall()}
    if "notice_chk" not in cols:
        conn.execute("ALTER TABLE biz_projects ADD COLUMN notice_chk INTEGER DEFAULT 0")
        print("[sync] add column: biz_projects.notice_chk (INTEGER DEFAULT 0)", flush=True)
    if "notice_order" not in cols:
        conn.execute("ALTER TABLE biz_projects ADD COLUMN notice_order INTEGER DEFAULT 0")
        print("[sync] add column: biz_projects.notice_order (INTEGER DEFAULT 0)", flush=True)
    if "notice_create_dt" not in cols:
        conn.execute("ALTER TABLE biz_projects ADD COLUMN notice_create_dt INTEGER")
        print("[sync] add column: biz_projects.notice_create_dt (INTEGER)", flush=True)


def _load_dump() -> Dict[str, Dict[str, Any]]:
    if not _DUMP.exists():
        raise FileNotFoundError(f"snapshot 없음: {_DUMP}")
    data = json.loads(_DUMP.read_text(encoding="utf-8"))
    out: Dict[str, Dict[str, Any]] = {}
    for r in data:
        url = r.get("url") or ""
        if not url:
            continue
        out[url] = r
    print(f"[sync] snapshot: {_DUMP.name} ({len(out)} rows, full schema)", flush=True)
    # 호환성: 신규 dump 인지 (3-필드 stub 인지) 확인
    sample = next(iter(out.values()))
    if "title" not in sample:
        raise RuntimeError(
            f"snapshot 형식 구버전 (3-필드 stub) — _check_dump_v1_jbtp.py 로 재생성 필요"
        )
    return out


def _print_distribution(conn: sqlite3.Connection, label: str) -> None:
    print(f"\n[sync] === {label} 분포 (운영 DB jbtp) ===", flush=True)
    total = conn.execute("SELECT COUNT(*) FROM biz_projects WHERE source='jbtp'").fetchone()[0]
    chk1 = conn.execute(
        "SELECT COUNT(*) FROM biz_projects WHERE source='jbtp' AND COALESCE(notice_chk,0)=1"
    ).fetchone()[0]
    sd_filled = conn.execute(
        "SELECT COUNT(*) FROM biz_projects WHERE source='jbtp' AND COALESCE(start_date,'')!=''"
    ).fetchone()[0]
    sd_2026 = conn.execute(
        "SELECT COUNT(*) FROM biz_projects WHERE source='jbtp' AND COALESCE(start_date,'')>='2026-01-01'"
    ).fetchone()[0]
    nord_nonzero = conn.execute(
        "SELECT COUNT(*) FROM biz_projects WHERE source='jbtp' AND COALESCE(notice_order,0)>0"
    ).fetchone()[0]
    print(f"  total: {total}", flush=True)
    print(f"  notice_chk=1: {chk1}", flush=True)
    print(f"  start_date 채워짐: {sd_filled}", flush=True)
    print(f"  start_date >= 2026-01-01: {sd_2026}", flush=True)
    print(f"  notice_order>0: {nord_nonzero}", flush=True)


def _print_widget_top(conn: sqlite3.Connection) -> None:
    """위젯 SQL 시뮬레이션 (공지 제외 top 5) — 사이트 seq 2198~2194 매칭 검증."""
    print("\n[sync] === 위젯 시뮬 (공지 제외 top 5) ===", flush=True)
    cur = conn.execute(
        """
        SELECT id, notice_chk, notice_order, start_date, title
        FROM biz_projects
        WHERE source='jbtp' AND COALESCE(notice_chk,0)=0
          AND COALESCE(start_date,'') >= '2026-01-01'
        ORDER BY COALESCE(notice_chk,0) DESC,
                 COALESCE(notice_order,0) DESC,
                 COALESCE(created_at,'') DESC, id DESC
        LIMIT 5
        """
    )
    for rid, nchk, nord, sd, title in cur.fetchall():
        t = (title or "")[:50]
        print(f"  id={rid} chk={nchk} oder={nord} sd={sd} title={t!r}", flush=True)


def _sync(
    conn: sqlite3.Connection,
    snapshot: Dict[str, Dict[str, Any]],
) -> Dict[str, int]:
    """v2 snapshot 을 운영 DB 로 UPSERT.

    UPDATE: 운영 url ∈ snapshot → 3 필드만 (049 merge 보호)
    INSERT: snapshot url ∉ 운영 → full row (052 패턴)
    """
    cur = conn.execute(
        "SELECT id, url, COALESCE(notice_chk,0), COALESCE(notice_order,0), "
        "COALESCE(start_date,'') FROM biz_projects WHERE source='jbtp'"
    )
    db_rows = cur.fetchall()
    print(f"[sync] DB jbtp row: {len(db_rows)}건", flush=True)

    db_urls = {url for _, url, _, _, _ in db_rows if url}
    snapshot_only_urls: List[str] = [u for u in snapshot.keys() if u not in db_urls]
    if snapshot_only_urls:
        print(
            f"[sync] snapshot 에만 있는 url {len(snapshot_only_urls)}건 → INSERT 대상",
            flush=True,
        )

    matched = 0
    updated = 0
    unchanged = 0
    no_match = 0

    # 1) UPDATE 경로
    for rid, url, db_chk, db_ord, db_sd in db_rows:
        if not url or url not in snapshot:
            no_match += 1
            continue
        matched += 1
        snap = snapshot[url]
        new_chk = int(snap.get("notice_chk") or 0)
        new_ord = int(snap.get("notice_order") or 0)
        new_sd = snap.get("start_date") or ""

        # 049 merge 보호: 새 값 0/'' + 옛 값 비-0/비-'' → 옛 값 보존
        merged_chk = new_chk
        if new_chk == 0 and int(db_chk or 0) != 0:
            merged_chk = int(db_chk or 0)
        merged_ord = new_ord
        if new_ord == 0 and int(db_ord or 0) != 0:
            merged_ord = int(db_ord or 0)
        merged_sd = new_sd
        if not new_sd and (db_sd or ""):
            merged_sd = db_sd

        if (
            int(db_chk or 0) == merged_chk
            and int(db_ord or 0) == merged_ord
            and (db_sd or "") == merged_sd
        ):
            unchanged += 1
            continue
        conn.execute(
            "UPDATE biz_projects SET "
            "notice_chk = ?, notice_order = ?, start_date = ?, "
            "updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (merged_chk, merged_ord, merged_sd, rid),
        )
        updated += 1

    # 2) INSERT 경로 (snapshot_only)
    inserted = 0
    snapshot_only_skip = 0
    for url in snapshot_only_urls:
        snap = snapshot[url]
        # 안전 가드: 핵심 필드 누락 시 skip
        if not (snap.get("title") or "").strip():
            print(f"[sync] INSERT skip (title 누락): {url[:80]}...", flush=True)
            snapshot_only_skip += 1
            continue
        vals: List[Any] = [snap.get(c) for c in INSERTABLE_COLS]
        cols_sql = ", ".join(INSERTABLE_COLS) + ", created_at, updated_at"
        placeholders = ", ".join(["?"] * len(INSERTABLE_COLS)) + ", CURRENT_TIMESTAMP, CURRENT_TIMESTAMP"
        try:
            conn.execute(
                f"INSERT INTO biz_projects ({cols_sql}) VALUES ({placeholders})",
                vals,
            )
            inserted += 1
        except sqlite3.IntegrityError as e:
            # url UNIQUE 충돌 등 — 정상 케이스에선 발생 안함 (db_urls 체크 통과)
            print(f"[sync] INSERT IntegrityError ({url[:60]}...): {e}", flush=True)
            snapshot_only_skip += 1

    return {
        "matched": matched,
        "updated": updated,
        "unchanged": unchanged,
        "no_match": no_match,
        "inserted": inserted,
        "snapshot_only_skip": snapshot_only_skip,
        "snapshot_only_total": len(snapshot_only_urls),
    }


def main() -> int:
    dry_run = os.getenv("DRY_RUN", "").strip() in ("1", "true", "True", "yes")
    db_path = _resolve_db_path()
    print(f"[sync] DB 경로: {db_path} (exists={db_path.exists()})", flush=True)
    print(f"[sync] DRY_RUN={dry_run}", flush=True)
    if not db_path.exists():
        print("[sync] DB 파일 없음 → 종료", flush=True)
        return 1

    snapshot = _load_dump()

    if not dry_run:
        _backup_db(db_path)
    else:
        print("[sync] DRY_RUN → 백업 생략", flush=True)

    conn = sqlite3.connect(str(db_path))
    try:
        _ensure_columns(conn)
        _print_distribution(conn, "BEFORE")
        result = _sync(conn, snapshot)
        _print_distribution(conn, "AFTER" if not dry_run else "AFTER (DRY_RUN 시뮬)")
        _print_widget_top(conn)
        if dry_run:
            conn.rollback()
            print("[sync] DRY_RUN → ROLLBACK (DB 미반영)", flush=True)
        else:
            conn.commit()
    finally:
        conn.close()

    print("\n[sync] === 결과 ===", flush=True)
    print(f"  matched (운영 DB url ∈ snapshot): {result['matched']}", flush=True)
    print(f"  updated: {result['updated']}", flush=True)
    print(f"  unchanged: {result['unchanged']}", flush=True)
    print(f"  inserted (snapshot only → 신규): {result['inserted']}", flush=True)
    print(f"  snapshot_only_skip (안전 가드 차단): {result['snapshot_only_skip']}", flush=True)
    print(f"  snapshot_only_total (운영 미존재 url): {result['snapshot_only_total']}", flush=True)
    print(f"  no_match (운영에 url 있지만 snapshot 외): {result['no_match']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
