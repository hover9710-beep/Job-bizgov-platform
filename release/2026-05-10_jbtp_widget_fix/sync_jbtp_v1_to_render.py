# -*- coding: utf-8 -*-
"""백로그 053 follow-up: v2 백필 ground-truth → 운영 DB sync (Render IP 차단 우회).

배경:
  053 백필 (backfill_jbtp.py) 가 사이트 9페이지 fetch 로 122 row 를 백필.
  v2 로컬 DB 에선 PASS. 운영 (Render Shell) 실행 시 ConnectTimeout —
  jbtp.or.kr 가 Render 해외 IP 차단 추정. 사이트 fetch 자체가 운영에서 막힘.

본 스크립트 = 단발성 우회. v2 로컬 DB (053 백필 apply 완료) 의 4 필드를
운영 DB 에 url 기준 UPDATE 로 sync. 052 sync_two_rows.py 패턴 차용.

대상 필드 (4개만):
  notice_chk, notice_order, start_date  (백로그 053 산출)
  나머지 모든 필드 (title, organization, status, ai_summary, ...) 는
  운영 row 그대로 보존 → 백로그 029 (connector divergence) 영향 0.

정책:
  - UPDATE only. 운영에 url 없는 v2 row 는 skip + count (운영 권위).
  - 멱등성: 같은 값이면 UPDATE 0. 두 번 실행해도 안전.
  - 사이트 영향: 0 (HTTP 호출 없음, JSON snapshot 사용).

실행 (Render Shell):
  DRY_RUN=1 python release/2026-05-10_jbtp_widget_fix/sync_jbtp_v1_to_render.py  # preview
  python release/2026-05-10_jbtp_widget_fix/sync_jbtp_v1_to_render.py            # apply

흐름:
  1) DB 자동 탐색 → SHA256 + 타임스탬프 백업 (DRY_RUN 시 생략)
  2) 컬럼 자동 보장 (notice_chk + notice_order ALTER, idempotent)
  3) JSON snapshot (v1_jbtp_dump.json) 로드 → {url: (chk, order, sd)}
  4) DB jbtp row 순회 → url 매칭 → 4 필드 UPDATE
  5) 결과 요약 (matched / updated / unchanged / no_match) + 위젯 시뮬
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
from typing import Dict, List, Tuple


_HERE = Path(__file__).resolve()
_ROOT = _HERE.parent.parent.parent
_DUMP = _HERE.parent / "v1_jbtp_dump.json"


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


def _load_dump() -> Dict[str, Tuple[int, int, str]]:
    if not _DUMP.exists():
        raise FileNotFoundError(f"snapshot 없음: {_DUMP}")
    data = json.loads(_DUMP.read_text(encoding="utf-8"))
    out: Dict[str, Tuple[int, int, str]] = {}
    for r in data:
        url = r.get("url") or ""
        if not url:
            continue
        out[url] = (
            int(r.get("notice_chk") or 0),
            int(r.get("notice_order") or 0),
            r.get("start_date") or "",
        )
    print(f"[sync] snapshot: {_DUMP.name} ({len(out)} rows)", flush=True)
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
    snapshot: Dict[str, Tuple[int, int, str]],
) -> Dict[str, int]:
    """v2 snapshot 4 필드를 운영 DB 로 UPDATE.

    정책: UPDATE only. 운영에 url 없는 v2 row 는 skip (운영 권위).
    DRY_RUN: UPDATE 실행 → 분포 측정 → 호출자 ROLLBACK.
    """
    cur = conn.execute(
        "SELECT id, url, COALESCE(notice_chk,0), COALESCE(notice_order,0), "
        "COALESCE(start_date,'') FROM biz_projects WHERE source='jbtp'"
    )
    db_rows = cur.fetchall()
    print(f"[sync] DB jbtp row: {len(db_rows)}건", flush=True)

    db_urls = {url for _, url, _, _, _ in db_rows if url}
    snapshot_only: List[str] = [u for u in snapshot.keys() if u not in db_urls]
    if snapshot_only:
        print(
            f"[sync] snapshot 에만 있는 url {len(snapshot_only)}건 (운영 미존재 → skip)",
            flush=True,
        )

    matched = 0
    updated = 0
    unchanged = 0
    no_match = 0

    for rid, url, db_chk, db_ord, db_sd in db_rows:
        if not url or url not in snapshot:
            no_match += 1
            continue
        matched += 1
        new_chk, new_ord, new_sd = snapshot[url]
        if (
            int(db_chk or 0) == new_chk
            and int(db_ord or 0) == new_ord
            and (db_sd or "") == new_sd
        ):
            unchanged += 1
            continue
        conn.execute(
            "UPDATE biz_projects SET "
            "notice_chk = ?, notice_order = ?, start_date = ?, "
            "updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (new_chk, new_ord, new_sd, rid),
        )
        updated += 1

    return {
        "matched": matched,
        "updated": updated,
        "unchanged": unchanged,
        "no_match": no_match,
        "snapshot_only": len(snapshot_only),
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
    print(f"  no_match (운영에 url 있지만 snapshot 외): {result['no_match']}", flush=True)
    print(f"  snapshot_only (snapshot 에 있지만 운영 미존재): {result['snapshot_only']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
