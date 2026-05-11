# -*- coding: utf-8 -*-
"""
biz_projects 에 synced_to_render / synced_at 컬럼 추가 (없을 때만).

백로그 057 Phase 2.1a — 운영 DB sync 메커니즘 (옵션 A: Incremental Sync) 의 기반 스키마.

- synced_to_render INTEGER DEFAULT 0
    : 0 = 미동기 (Render 운영 DB 에 아직 반영 안 됨)
    : 1 = 동기 완료
    : connector INSERT / appy UPDATE 시 0 으로 reset, sync 성공 응답 시 1
- synced_at TIMESTAMP (NULL 허용)
    : 마지막 성공 sync 시각 (재시도 추적, 통계 재료)

기존 데이터는 유지됩니다. 멱등 (재실행 안전).

실행(프로젝트 루트):
  py scripts/migrate_add_sync_columns.py
  py scripts/migrate_add_sync_columns.py --db path/to/biz.db
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
    ("synced_to_render", "INTEGER DEFAULT 0", "Render 운영 DB 동기 여부 (0=미동기, 1=동기)"),
    ("synced_at", "TIMESTAMP", "마지막 성공 sync 시각 (NULL=미동기)"),
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
    print(f"[migrate_add_sync_columns] DB: {db_path.resolve()}")
    if not db_path.exists():
        print("[migrate_add_sync_columns] ERROR: 파일이 없습니다. 경로를 확인하세요.")
        raise SystemExit(1)

    conn = sqlite3.connect(db_path)
    try:
        table = "biz_projects"
        if not _table_exists(conn, table):
            print(f"[migrate_add_sync_columns] ERROR: 테이블 없음 → {table}")
            raise SystemExit(2)

        cols = _column_names(conn, table)
        n_before = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        print(f"[migrate_add_sync_columns] 테이블 {table}: 행 수 {n_before}건")

        for col, col_type, label in NEW_COLUMNS:
            if col in cols:
                print(f"  [OK] 이미 있음: {table}.{col} ({label})")
                continue
            print(f"  [+] 추가 중: {table}.{col} {col_type} ({label}) …")
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
            cols.add(col)
            print(f"  [완료] {table}.{col}")

        conn.commit()

        # 검증: 새 컬럼이 모두 default 값으로 채워졌는지 확인
        n_pending = int(
            conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE synced_to_render = 0"
            ).fetchone()[0]
        )
        n_synced_at_null = int(
            conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE synced_at IS NULL"
            ).fetchone()[0]
        )
        print(
            f"[migrate_add_sync_columns] 검증: synced_to_render=0 행 {n_pending}건 / "
            f"synced_at IS NULL 행 {n_synced_at_null}건 (각각 전체 {n_before}건과 일치 기대)"
        )
        if n_pending != n_before or n_synced_at_null != n_before:
            print(
                "[migrate_add_sync_columns] WARN: 일부 행에 default 가 적용되지 않음 — "
                "이전 마이그레이션 흔적일 가능성. 수동 확인 필요."
            )
        else:
            print("[migrate_add_sync_columns] 검증 PASS: 전체 행이 default 상태")

        print("[migrate_add_sync_columns] 커밋 완료. 기존 행 데이터는 그대로 유지됩니다.")
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(
        description="synced_to_render / synced_at 컬럼 마이그레이션 (백로그 057 Phase 2.1a)"
    )
    ap.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite 경로")
    args = ap.parse_args()
    migrate(args.db.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
