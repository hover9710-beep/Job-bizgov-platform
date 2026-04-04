"""
기존 db/biz.db 의 biz_projects 에 잘못 들어간 organization 을
merge_jb._normalize_item 과 동일한 규칙으로 재계산해 갱신합니다.

실행(프로젝트 루트):
  py pipeline\\backfill_organization.py
  py pipeline\\backfill_organization.py --apply

옵션:
  --apply  실제 DB 갱신 (없으면 변경 건수만 출력)
  --table  기본 biz_projects (동일 스키마의 projects 등)
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from pipeline.merge_jb import _normalize_item  # noqa: E402
from pipeline.update_db import DB_PATH, _init_db  # noqa: E402


def _row_to_synthetic(row: sqlite3.Row) -> Dict[str, Any]:
    """저장된 organization 은 넣지 않음(재계산 대상)."""
    url = str(row["url"] or "").strip()
    desc = str(row["description"] or "").strip()
    sd = str(row["start_date"] or "").strip()
    ed = str(row["end_date"] or "").strip()
    period = ""
    if sd or ed:
        period = f"{sd} ~ {ed}"
    return {
        "title": str(row["title"] or "").strip(),
        "url": url,
        "상세URL": url,
        "description": desc,
        "body": desc,
        "summary": desc,
        "status": str(row["status"] or "").strip(),
        "기간": period,
        "period": period,
    }


def recompute_organization(row: sqlite3.Row) -> str:
    synthetic = _row_to_synthetic(row)
    url = str(row["url"] or "").strip()
    desc = str(row["description"] or "").strip()
    old_org = str(row["organization"] or "").strip()
    # URL 이 비어 있으면 merge 단계의 is_bizinfo 판별이 어긋날 수 있음 → 힌트 보강
    hint = url
    if not url:
        if old_org == "기업마당":
            hint = "bizinfo"
        elif "bizinfo.go.kr" in desc or "www.bizinfo.go.kr" in desc.lower():
            hint = "bizinfo"
        elif "jbexport.or.kr" in desc:
            hint = "https://www.jbexport.or.kr"
    norm = _normalize_item(synthetic, source_hint=hint)
    return str(norm.get("organization") or "").strip()


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(c[1]) for c in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def backfill(table: str, apply: bool) -> Tuple[int, int, int]:
    """
    반환: (총 행 수, 변경 대상 수, 실제 갱신 수)
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        _init_db(conn)
        cur = conn.cursor()
        if not cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone():
            raise SystemExit(f"[backfill] 테이블 없음: {table}")
        cols = _table_columns(conn, table)
        required = {"id", "organization", "title", "url", "description", "start_date", "end_date", "status"}
        if not required.issubset(cols):
            raise SystemExit(f"[backfill] {table} 에 필요한 컬럼이 없습니다: {sorted(required - cols)}")
        has_updated_at = "updated_at" in cols

        rows = cur.execute(
            f"""
            SELECT id, title, organization, url, description, start_date, end_date, status
            FROM {table}
            ORDER BY id
            """
        ).fetchall()

        changed = 0
        updated = 0
        for row in rows:
            old = str(row["organization"] or "").strip()
            new = recompute_organization(row)
            if old != new:
                changed += 1
                if apply:
                    if has_updated_at:
                        cur.execute(
                            f"""
                            UPDATE {table}
                            SET organization = ?, updated_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                            """,
                            (new, row["id"]),
                        )
                    else:
                        cur.execute(
                            f"UPDATE {table} SET organization = ? WHERE id = ?",
                            (new, row["id"]),
                        )
                    updated += cur.rowcount
        if apply:
            conn.commit()
        return len(rows), changed, updated
    finally:
        conn.close()


def main() -> None:
    p = argparse.ArgumentParser(description="biz_projects organization 재정규화")
    p.add_argument("--table", default="biz_projects", help="대상 테이블명")
    p.add_argument("--apply", action="store_true", help="실제 DB 갱신")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="미리보기만 (기본 동작과 동일, 명시용)",
    )
    args = p.parse_args()
    if args.apply and args.dry_run:
        p.error("--apply 와 --dry-run 을 함께 쓸 수 없습니다.")

    total, changed, updated = backfill(args.table, apply=args.apply)
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[backfill_organization] mode={mode} table={args.table} db={DB_PATH}")
    print(f"[backfill_organization] 총 {total}건, organization 변경 대상 {changed}건")
    if args.apply:
        print(f"[backfill_organization] 갱신 완료 {updated}건")
    else:
        print("[backfill_organization] DB 미변경. 적용하려면 --apply")


if __name__ == "__main__":
    main()
