# -*- coding: utf-8 -*-
"""
biz_projects(source of truth) → projects(mirror) 전체 복제.
스키마는 biz_projects 와 동일하게 복제한 뒤 INSERT SELECT * 로 복사.

실행(프로젝트 루트):
  py pipeline/mirror_projects.py
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Any, Dict, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT_DIR / "db" / "biz.db"

KNOWN = frozenset({"jbexport", "bizinfo", "jbba", "jbtp", "kotra", "unknown"})


def classify_source(raw: Any) -> str:
    if raw is None:
        return "unknown"
    s = str(raw).strip().lower()
    if not s:
        return "unknown"
    if s in KNOWN:
        return s
    return "unknown"


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def source_distribution(conn: sqlite3.Connection, table: str) -> Tuple[int, int, int]:
    """jbexport / bizinfo / none 건수."""
    if not _table_exists(conn, table):
        return 0, 0, 0
    cols = {str(c[1]) for c in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if "source" not in cols:
        n = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        return 0, 0, n
    jb = bi = no = 0
    for (raw,) in conn.execute(f"SELECT source FROM {table}"):
        lab = classify_source(raw)
        if lab == "jbexport":
            jb += 1
        elif lab == "bizinfo":
            bi += 1
        else:
            no += 1
    return jb, bi, no


def mirror_biz_projects_to_projects(conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    projects 테이블을 biz_projects 스냅샷과 동일하게 만든다.
    DROP → CREATE AS SELECT(빈) → INSERT SELECT * 로 스키마·데이터 일치.
    """
    if not _table_exists(conn, "biz_projects"):
        return {
            "skipped": 1,
            "source_rows": 0,
            "target_before": 0,
            "target_after": 0,
            "biz_jbexport": 0,
            "biz_bizinfo": 0,
            "biz_none": 0,
            "proj_jbexport": 0,
            "proj_bizinfo": 0,
            "proj_none": 0,
        }

    source_rows = int(conn.execute("SELECT COUNT(*) FROM biz_projects").fetchone()[0])
    bj, bb, bn = source_distribution(conn, "biz_projects")

    target_before = 0
    if _table_exists(conn, "projects"):
        target_before = int(conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0])

    conn.execute("DROP TABLE IF EXISTS projects")
    conn.execute(
        "CREATE TABLE projects AS SELECT * FROM biz_projects WHERE 1=0"
    )
    conn.execute("INSERT INTO projects SELECT * FROM biz_projects")

    target_after = int(conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0])
    pj, pb, pn = source_distribution(conn, "projects")

    print(f"[mirror_projects] source rows (biz_projects): {source_rows}")
    print(f"[mirror_projects] target rows before: {target_before}")
    print(f"[mirror_projects] target rows after: {target_after}")
    print(
        f"[mirror_projects] biz_projects source: jbexport={bj}, bizinfo={bb}, other={bn}"
    )
    print(
        f"[mirror_projects] projects source: jbexport={pj}, bizinfo={pb}, other={pn}"
    )

    return {
        "skipped": 0,
        "source_rows": source_rows,
        "target_before": target_before,
        "target_after": target_after,
        "biz_jbexport": bj,
        "biz_bizinfo": bb,
        "biz_none": bn,
        "proj_jbexport": pj,
        "proj_bizinfo": pb,
        "proj_none": pn,
        "inserted": target_after,
        "before": target_before,
        "deleted": target_before,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="biz_projects → projects 미러링")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite 경로")
    args = parser.parse_args()
    db_path = args.db.resolve()
    conn = sqlite3.connect(db_path)
    try:
        stats = mirror_biz_projects_to_projects(conn)
        conn.commit()
    finally:
        conn.close()
    print(f"[mirror_projects] db={db_path} skipped={stats.get('skipped', 0)}")


if __name__ == "__main__":
    main()
