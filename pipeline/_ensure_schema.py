# -*- coding: utf-8 -*-
"""biz.db 스키마 통합 ensure (백로그 065 Phase 2-Pre).

GitHub Actions / PC / 운영 환경 간 스키마 divergence 의 구조적 차단.
appy.py 의 두 ALTER 패턴 (_ensure_column line-by-line + _safe_add 23건) 을 단일
모듈로 통합 — connector / pipeline / yaml init 어디서나 import 호출.

호출:
    from pipeline._ensure_schema import ensure_schema
    conn = sqlite3.connect(db_path)
    ensure_schema(conn)

CLI (Actions yaml init step / 수동 검증):
    py pipeline/_ensure_schema.py
    py pipeline/_ensure_schema.py --db path/to/biz.db
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

# (table, column, coltype) — appy.py:121-156 line-by-line + appy.py:319-346 _safe_add 통합.
COLUMNS: tuple[tuple[str, str, str], ...] = (
    # biz_projects (appy.py:121-156)
    ("biz_projects", "organization", "TEXT"),
    ("biz_projects", "source", "TEXT"),
    ("biz_projects", "ministry", "TEXT"),
    ("biz_projects", "executing_agency", "TEXT"),
    ("biz_projects", "receipt_start", "TEXT"),
    ("biz_projects", "receipt_end", "TEXT"),
    ("biz_projects", "biz_start", "TEXT"),
    ("biz_projects", "biz_end", "TEXT"),
    ("biz_projects", "raw_status", "TEXT"),
    ("biz_projects", "attachments_json", "TEXT"),
    ("biz_projects", "notice_create_dt", "INTEGER"),
    ("biz_projects", "notice_chk", "INTEGER DEFAULT 0"),
    ("biz_projects", "notice_order", "INTEGER DEFAULT 0"),
    ("biz_projects", "synced_to_render", "INTEGER DEFAULT 0"),
    ("biz_projects", "synced_at", "TIMESTAMP"),
    # biz_projects (appy.py:319-340 _safe_add)
    ("biz_projects", "ai_result", "TEXT"),
    ("biz_projects", "pdf_path", "TEXT"),
    ("biz_projects", "site", "TEXT"),
    ("biz_projects", "collected_at", "TEXT"),
    ("biz_projects", "ai_summary", "TEXT"),
    ("biz_projects", "ai_summary_at", "TEXT"),
    ("biz_projects", "recommend_label", "TEXT"),
    ("biz_projects", "recommend_label_at", "TEXT"),
    ("biz_projects", "period_text", "TEXT"),
    ("biz_projects", "attachment_text", "TEXT"),
    ("biz_projects", "score", "REAL"),
    ("biz_projects", "reason", "TEXT"),
    ("biz_projects", "apply_url", "TEXT"),
    ("biz_projects", "view_count", "INTEGER DEFAULT 0"),
    # companies (appy.py:342-346)
    ("companies", "social_enterprise", "INTEGER DEFAULT 0"),
    ("companies", "female_ceo", "INTEGER DEFAULT 0"),
    ("companies", "export_tower", "INTEGER DEFAULT 0"),
    ("companies", "cert_count", "INTEGER DEFAULT 0"),
    ("companies", "catalog_count", "INTEGER DEFAULT 0"),
    # visit_log / click_log (appy.py:296-297)
    ("visit_log", "traffic_source", "TEXT"),
    ("click_log", "traffic_source", "TEXT"),
)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(c[1]) for c in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def ensure_schema(conn: sqlite3.Connection, *, verbose: bool = False) -> dict[str, int]:
    """모든 컬럼이 존재하도록 ALTER. 멱등. Returns: {added, skipped_existing, skipped_no_table}."""
    added = 0
    skipped_existing = 0
    skipped_no_table = 0
    by_table_cache: dict[str, set[str]] = {}

    for table, col, coltype in COLUMNS:
        if not _table_exists(conn, table):
            skipped_no_table += 1
            if verbose:
                print(f"  [skip] {table} 없음 — {table}.{col} 패스")
            continue
        if table not in by_table_cache:
            by_table_cache[table] = _column_names(conn, table)
        cols = by_table_cache[table]
        if col in cols:
            skipped_existing += 1
            continue
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
            cols.add(col)
            added += 1
            if verbose:
                print(f"  [+] {table}.{col} {coltype}")
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e).lower():
                cols.add(col)
                skipped_existing += 1
            else:
                raise

    conn.commit()
    return {
        "added": added,
        "skipped_existing": skipped_existing,
        "skipped_no_table": skipped_no_table,
    }


def ensure_schema_path(db_path: str | Path, *, verbose: bool = False) -> dict[str, int]:
    p = Path(db_path)
    if not p.exists():
        if verbose:
            print(f"[ensure_schema] DB 없음 — 신규 생성: {p}")
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    try:
        return ensure_schema(conn, verbose=verbose)
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(
        description="biz.db 스키마 통합 ensure (백로그 065 Phase 2-Pre)"
    )
    ap.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite 경로")
    ap.add_argument("--quiet", action="store_true", help="컬럼별 출력 억제")
    args = ap.parse_args()
    print(f"[ensure_schema] DB: {args.db.resolve()}")
    result = ensure_schema_path(args.db.resolve(), verbose=not args.quiet)
    print(
        f"[ensure_schema] 완료: added={result['added']} "
        f"skipped_existing={result['skipped_existing']} "
        f"skipped_no_table={result['skipped_no_table']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
