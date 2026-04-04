# -*- coding: utf-8 -*-
"""
recommendations 테이블 생성 (없을 때만).

실행:
  py scripts/migrate_recommendations.py
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "biz.db"

SQL = """
CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    project_id INTEGER NOT NULL,
    score INTEGER NOT NULL DEFAULT 0,
    reason TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, project_id)
)
"""


def main() -> int:
    if sys.platform == "win32":
        for s in (sys.stdout, sys.stderr):
            try:
                s.reconfigure(encoding="utf-8")
            except Exception:
                pass

    ap = argparse.ArgumentParser(description="recommendations 테이블 마이그레이션")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = ap.parse_args()
    db_path = args.db.resolve()

    print(f"[migrate_recommendations] DB: {db_path}")
    if not db_path.exists():
        print("[migrate_recommendations] ERROR: DB 없음")
        return 1

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(SQL)
        conn.commit()
        print("[migrate_recommendations] OK: recommendations 테이블 준비됨")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
