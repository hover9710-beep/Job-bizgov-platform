# -*- coding: utf-8 -*-
"""
biz_projects / projects 에 ministry, executing_agency 컬럼 추가 (없을 때만).
기존 데이터는 유지됩니다.

실행(프로젝트 루트):
  py scripts/migrate_add_agency_fields.py
  py scripts/migrate_add_agency_fields.py --db path/to/biz.db
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "biz.db"

NEW_COLUMNS = (
    ("ministry", "소관부처"),
    ("executing_agency", "사업수행기관/지원기관"),
)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(c[1]) for c in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def migrate(db_path: Path) -> None:
    print(f"[migrate_add_agency_fields] DB: {db_path.resolve()}")
    if not db_path.exists():
        print("[migrate_add_agency_fields] ERROR: 파일이 없습니다. 경로를 확인하세요.")
        raise SystemExit(1)

    conn = sqlite3.connect(db_path)
    try:
        for table in ("biz_projects", "projects"):
            if not _table_exists(conn, table):
                print(f"[migrate_add_agency_fields] 건너뜀: 테이블 없음 → {table}")
                continue
            cols = _column_names(conn, table)
            n_before = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            print(f"[migrate_add_agency_fields] 테이블 {table}: 행 수 {n_before}건")
            for col, label in NEW_COLUMNS:
                if col in cols:
                    print(f"  [OK] 이미 있음: {table}.{col} ({label})")
                    continue
                print(f"  [+] 추가 중: {table}.{col} ({label}) …")
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT")
                cols.add(col)
                print(f"  [완료] {table}.{col}")
        conn.commit()
        print("[migrate_add_agency_fields] 커밋 완료. 기존 행 데이터는 그대로 유지됩니다.")
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="ministry / executing_agency 컬럼 마이그레이션")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite 경로")
    args = ap.parse_args()
    migrate(args.db.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
