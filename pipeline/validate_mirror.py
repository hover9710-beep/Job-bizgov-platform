# -*- coding: utf-8 -*-
"""
biz_projects(source of truth) vs projects(mirror) 일치 검증.

실행(프로젝트 루트):
  py pipeline/validate_mirror.py
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Any, List, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent
_PIPELINE_DIR = Path(__file__).resolve().parent
if str(_PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_DIR))

from mirror_projects import _table_exists, source_distribution

DEFAULT_DB = ROOT_DIR / "db" / "biz.db"


def _row_sample(
    conn: sqlite3.Connection, table: str, n: int = 5
) -> List[Tuple[Any, ...]]:
    if not _table_exists(conn, table):
        return []
    cols = [str(c[1]) for c in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    need = ["id", "title", "source"]
    sel = [c for c in need if c in cols]
    if not sel:
        return []
    q = "SELECT " + ", ".join(sel) + f" FROM {table} ORDER BY id LIMIT ?"
    return list(conn.execute(q, (n,)))


def main() -> int:
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass

    parser = argparse.ArgumentParser(description="biz_projects ↔ projects 미러 검증")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    db_path = args.db.resolve()

    conn = sqlite3.connect(db_path)
    try:
        if not _table_exists(conn, "biz_projects"):
            print("FAIL: biz_projects 테이블 없음")
            return 1
        if not _table_exists(conn, "projects"):
            print("FAIL: projects 테이블 없음 (mirror 미실행?)")
            return 1

        biz_n = int(conn.execute("SELECT COUNT(*) FROM biz_projects").fetchone()[0])
        proj_n = int(conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0])
        bj, bb, bn = source_distribution(conn, "biz_projects")
        pj, pb, pn = source_distribution(conn, "projects")

        ok = (
            biz_n == proj_n
            and bj == pj
            and bb == pb
            and bn == pn
        )

        print("=== validate_mirror ===")
        print(f"biz_projects rows: {biz_n}")
        print(f"projects rows: {proj_n}")
        print(f"biz_projects source: jbexport={bj}, bizinfo={bb}, 기타={bn}")
        print(f"projects source: jbexport={pj}, bizinfo={pb}, 기타={pn}")

        samples_ok = True
        biz_s = _row_sample(conn, "biz_projects", 5)
        print("\n[sample id, title, source] (최대 5건)")
        for i, br in enumerate(biz_s):
            bid = br[0]
            pr = conn.execute(
                "SELECT id, title, source FROM projects WHERE id = ?",
                (bid,),
            ).fetchone()
            if pr is None:
                print(f"  id={bid} FAIL: projects에 행 없음")
                samples_ok = False
                continue
            if (br[0], br[1], br[2] if len(br) > 2 else None) != (
                pr[0],
                pr[1],
                pr[2] if len(pr) > 2 else None,
            ):
                print(f"  id={bid} MISMATCH biz={br} proj={pr}")
                samples_ok = False
            else:
                t = (br[1] or "")[:40]
                print(f"  id={bid} OK title={t!r}...")

        if ok and samples_ok:
            print("\nresult: PASS")
            return 0
        reasons: List[str] = []
        if biz_n != proj_n:
            reasons.append("row count mismatch")
        if (bj, bb, bn) != (pj, pb, pn):
            reasons.append("source distribution mismatch")
        if not samples_ok:
            reasons.append("sample row mismatch")
        print(f"\nresult: FAIL")
        print(f"reason: {'; '.join(reasons) or 'unknown'}")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
