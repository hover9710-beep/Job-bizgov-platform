# -*- coding: utf-8 -*-
"""
biz_projects 테이블 컬럼 확인 — ministry, executing_agency 존재 여부.

실행:
  py scripts/validate_biz_projects_schema.py
  py scripts/validate_biz_projects_schema.py --db path/to/biz.db
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "biz.db"

REQUIRED = ("ministry", "executing_agency")


def main() -> int:
    if sys.platform == "win32":
        for s in (sys.stdout, sys.stderr):
            try:
                s.reconfigure(encoding="utf-8")
            except Exception:
                pass

    ap = argparse.ArgumentParser(description="biz_projects 스키마 검증")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = ap.parse_args()
    db_path = args.db.resolve()

    print(f"[validate_biz_projects_schema] DB: {db_path}")
    if not db_path.exists():
        print("[validate_biz_projects_schema] ERROR: DB 파일이 없습니다.")
        return 1

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='biz_projects'"
        ).fetchone()
        if not row:
            print("[validate_biz_projects_schema] ERROR: biz_projects 테이블이 없습니다.")
            return 1

        cols = [str(c[1]) for c in conn.execute("PRAGMA table_info(biz_projects)").fetchall()]
        print("[validate_biz_projects_schema] 현재 컬럼:")
        for c in cols:
            print(f"  - {c}")

        missing = [c for c in REQUIRED if c not in cols]
        if missing:
            print(f"[validate_biz_projects_schema] FAIL: 누락 컬럼 → {missing}")
            print("  → py scripts/migrate_add_agency_fields.py 실행 후 다시 확인하세요.")
            return 2

        print("[validate_biz_projects_schema] OK: ministry, executing_agency 컬럼이 있습니다.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
