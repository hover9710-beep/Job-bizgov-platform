# -*- coding: utf-8 -*-
"""
백로그 057 Phase 2.1c — v1 master → Render 운영 DB sync 호출자.

흐름:
  1. v1 로컬 DB 에서 WHERE synced_to_render = 0 row 조회 (source 별)
  2. source 별로 그룹 + N 행 batch
  3. POST /api/sync (ADMIN_KEY 인증, JSON body)
  4. 성공 응답 (HTTP 200 + ok=true) → 해당 batch row 들의 synced_to_render = 1, synced_at = CURRENT_TIMESTAMP UPDATE
  5. 실패 (network / non-200 / ok=false) → 미갱신, 다음 실행 시 재시도 (멱등성)

정책 (백로그 057 Phase 2):
  - Incremental sync (변경분만)
  - url unique 기준 UPSERT (server-side)
  - synced_to_render flag = 단일 delta 추적 (notice_order ≠ sync 기준)
  - Empty payload skip (rows=0 → POST 자체 skip)
  - 동적 테이블 절대 미터치 (server-side enforcement)
  - 운영 enrich 컬럼 미전송 (whitelist 만 보냄)

실행 예시:

  # dry-run (DB 변경 없음, POST 없음, 분포만 출력)
  py pipeline/sync_to_render.py --dry-run

  # 특정 source 만
  py pipeline/sync_to_render.py --source jbtp --source jbexport

  # 운영 URL 명시 (기본: 환경변수 RENDER_URL 또는 https://job-bizgov-platform.onrender.com)
  py pipeline/sync_to_render.py --render-url https://job-bizgov-platform.onrender.com

  # 로컬 dev appy.py 대상 (검증)
  py pipeline/sync_to_render.py --render-url http://localhost:5000

  # ADMIN_KEY 명시 (기본: 환경변수 ADMIN_KEY 또는 dev-admin-key)
  py pipeline/sync_to_render.py --admin-key <KEY>

환경변수:
  DB_PATH       SQLite 경로 (기본: db/biz.db)
  RENDER_URL    sync 대상 base URL (기본: 운영)
  ADMIN_KEY     /api/sync 인증 키 (기본: dev-admin-key)

반환 코드:
  0  성공 (한 batch 라도 실패 시에도 0 — 다음 실행이 재시도)
  1  치명적 (DB 없음, ADMIN_KEY 누락 등)
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Iterable

import requests

if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "biz.db"

# PC 로컬 실행 시 .env 의 ADMIN_KEY / RENDER_URL 자동 로드 (백로그 066 사이클 2, 2026-05-17).
# Actions / Render 는 환경변수 직접 설정 — load_dotenv 는 .env 없으면 no-op.
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass
DEFAULT_RENDER_URL = "https://job-bizgov-platform.onrender.com"
DEFAULT_BATCH_SIZE = 500
DEFAULT_TIMEOUT = 60  # seconds — Render cold start 고려

# /api/sync 가 받아주는 컬럼 (server-side SYNC_UPDATE_WHITELIST 동기화 — appy.py 와 함께 갱신)
# url 은 매칭 키로 항상 포함.
#
# 정책 (백로그 066 Phase 2-Alpha, 2026-05-17 갱신):
#  - 사이트 master 데이터 + v1 결정 표시 데이터 양쪽 sync.
#  - 운영 enrich (서버가 무시): id, created_at, updated_at, view_count, ai_summary,
#    ai_summary_at, recommend_*, attachment_text, score, reason, synced_*.
#  - v1 master 결정 표시 데이터 (sync 포함): ai_friendly_title, ai_friendly_summary.
#    → v1 PC 에서 1회 일괄 GPT-4o-mini 통역 후 운영 반영, 운영은 통역 미실행.
SYNC_FIELDS = (
    "url",
    "title",
    "organization",
    "start_date",
    "end_date",
    "status",
    "description",
    "source",
    "site",
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
    "apply_url",
    "pdf_path",
    "notice_create_dt",
    "notice_chk",
    "notice_order",
    # AI 언어 통역 (v1 master, 백로그 066 Phase 2-Alpha):
    "ai_friendly_title",
    "ai_friendly_summary",
)


def resolve_db_path(arg: Path | None) -> Path:
    if arg:
        return arg
    env = (os.getenv("DB_PATH") or "").strip()
    if env:
        return Path(env)
    return DEFAULT_DB


def resolve_render_url(arg: str | None) -> str:
    if arg:
        return arg.rstrip("/")
    env = (os.getenv("RENDER_URL") or "").strip()
    if env:
        return env.rstrip("/")
    return DEFAULT_RENDER_URL


def resolve_admin_key(arg: str | None) -> str:
    if arg:
        return arg
    return os.getenv("ADMIN_KEY", "dev-admin-key")


def fetch_pending(
    conn: sqlite3.Connection,
    source_filter: Iterable[str] | None,
) -> list[dict[str, Any]]:
    cols_sql = ", ".join(("id", *SYNC_FIELDS))
    query = f"SELECT {cols_sql} FROM biz_projects WHERE COALESCE(synced_to_render, 0) = 0"
    params: list[Any] = []
    filters = list(source_filter or [])
    if filters:
        placeholders = ",".join("?" * len(filters))
        query += f" AND source IN ({placeholders})"
        params.extend(filters)
    query += " ORDER BY source, id"

    cursor = conn.execute(query, params)
    keys = ("id", *SYNC_FIELDS)
    rows: list[dict[str, Any]] = []
    for raw in cursor.fetchall():
        rows.append(dict(zip(keys, raw)))
    return rows


def group_by_source(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        src = row.get("source") or "<unknown>"
        out.setdefault(src, []).append(row)
    return out


def batch_iter(rows: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


def to_payload_row(row: dict[str, Any]) -> dict[str, Any]:
    return {k: row[k] for k in SYNC_FIELDS if row.get(k) is not None}


def mark_synced(conn: sqlite3.Connection, row_ids: list[int]) -> int:
    if not row_ids:
        return 0
    placeholders = ",".join("?" * len(row_ids))
    cur = conn.execute(
        f"UPDATE biz_projects SET synced_to_render = 1, synced_at = CURRENT_TIMESTAMP "
        f"WHERE id IN ({placeholders})",
        row_ids,
    )
    conn.commit()
    return cur.rowcount


def post_batch(
    session: requests.Session,
    render_url: str,
    admin_key: str,
    source: str,
    rows: list[dict[str, Any]],
    timeout: int,
) -> tuple[bool, dict[str, Any] | None, str | None]:
    """POST /api/sync. 성공 시 (True, body, None), 실패 시 (False, body_or_None, error_msg)."""
    url = f"{render_url}/api/sync"
    payload = {
        "key": admin_key,
        "source": source,
        "rows": [to_payload_row(r) for r in rows],
    }
    try:
        resp = session.post(url, json=payload, timeout=timeout)
    except requests.exceptions.RequestException as e:
        return False, None, f"network: {e!r}"
    try:
        body = resp.json()
    except ValueError:
        body = {"_raw": resp.text[:300]}
    if resp.status_code != 200:
        return False, body, f"HTTP {resp.status_code}"
    if not body.get("ok"):
        return False, body, f"ok=false: {body.get('error')}"
    return True, body, None


def run(
    db_path: Path,
    render_url: str,
    admin_key: str,
    source_filter: list[str],
    batch_size: int,
    timeout: int,
    dry_run: bool,
) -> int:
    print(f"[sync_to_render] DB: {db_path}")
    print(f"[sync_to_render] target: {render_url}")
    print(f"[sync_to_render] ADMIN_KEY: {'*' * (len(admin_key) - 2)}{admin_key[-2:]}")
    print(f"[sync_to_render] batch_size: {batch_size}, timeout: {timeout}s, dry_run: {dry_run}")
    if source_filter:
        print(f"[sync_to_render] source filter: {source_filter}")

    if not db_path.exists():
        print(f"[sync_to_render] ERROR: DB 없음 → {db_path}")
        return 1
    if not admin_key:
        print("[sync_to_render] ERROR: ADMIN_KEY 누락")
        return 1

    conn = sqlite3.connect(db_path)
    try:
        # 새 컬럼 존재 확인
        cols = {str(c[1]) for c in conn.execute("PRAGMA table_info(biz_projects)").fetchall()}
        if "synced_to_render" not in cols or "synced_at" not in cols:
            print(
                "[sync_to_render] ERROR: synced_to_render / synced_at 컬럼 없음 → "
                "scripts/migrate_add_sync_columns.py 먼저 실행"
            )
            return 1

        pending = fetch_pending(conn, source_filter or None)
        if not pending:
            print("[sync_to_render] pending 없음 (모든 row 가 이미 synced_to_render=1)")
            return 0

        by_source = group_by_source(pending)
        print(f"[sync_to_render] pending 총 {len(pending)}건, source {len(by_source)}개:")
        for src, rows in by_source.items():
            print(f"  - {src}: {len(rows)}건")

        if dry_run:
            print("\n[sync_to_render] DRY_RUN — POST / DB UPDATE 건너뜀.")
            sample = next(iter(by_source.values()))[0]
            sample_payload = to_payload_row(sample)
            print(
                f"[sync_to_render] 샘플 payload (1 row, source={sample['source']}):\n"
                f"{json.dumps(sample_payload, ensure_ascii=False, indent=2, default=str)[:500]}"
            )
            return 0

        session = requests.Session()
        totals = {
            "inserted": 0,
            "updated": 0,
            "errors": 0,
            "batches_ok": 0,
            "batches_fail": 0,
            "marked_synced": 0,
        }

        for src, rows in by_source.items():
            print(f"\n[sync_to_render] === source={src} ({len(rows)}건) ===")
            for batch_idx, batch in enumerate(batch_iter(rows, batch_size), start=1):
                ok, body, err = post_batch(
                    session, render_url, admin_key, src, batch, timeout
                )
                if not ok:
                    totals["batches_fail"] += 1
                    print(
                        f"  [FAIL] batch {batch_idx} ({len(batch)}건) — {err}; "
                        f"body={body}"
                    )
                    continue
                inserted = int(body.get("inserted", 0))
                updated = int(body.get("updated", 0))
                errs = body.get("errors") or []
                totals["inserted"] += inserted
                totals["updated"] += updated
                totals["errors"] += len(errs)
                totals["batches_ok"] += 1
                marked = mark_synced(conn, [r["id"] for r in batch])
                totals["marked_synced"] += marked
                print(
                    f"  [OK] batch {batch_idx} ({len(batch)}건) — "
                    f"inserted={inserted}, updated={updated}, "
                    f"row_errors={len(errs)}, marked_synced={marked}"
                )
                if errs:
                    print(f"      row errors (최대 3): {errs[:3]}")

        print("\n[sync_to_render] === 결과 ===")
        for k, v in totals.items():
            print(f"  {k}: {v}")

        remaining = int(
            conn.execute(
                "SELECT COUNT(*) FROM biz_projects WHERE COALESCE(synced_to_render, 0) = 0"
            ).fetchone()[0]
        )
        print(f"  pending after run: {remaining}")
        return 0
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(
        description="v1 master → Render 운영 DB sync (백로그 057 Phase 2.1c)"
    )
    ap.add_argument("--db", type=Path, default=None, help="SQLite 경로 (기본: db/biz.db 또는 $DB_PATH)")
    ap.add_argument(
        "--render-url",
        default=None,
        help=f"sync 대상 base URL (기본: $RENDER_URL 또는 {DEFAULT_RENDER_URL})",
    )
    ap.add_argument(
        "--admin-key",
        default=None,
        help="/api/sync ADMIN_KEY (기본: $ADMIN_KEY 또는 dev-admin-key)",
    )
    ap.add_argument(
        "--source",
        action="append",
        default=[],
        help="source 필터 (반복 가능). 미지정 시 전체.",
    )
    ap.add_argument(
        "--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help=f"기본 {DEFAULT_BATCH_SIZE}"
    )
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help=f"기본 {DEFAULT_TIMEOUT}s")
    ap.add_argument("--dry-run", action="store_true", help="POST / DB UPDATE 안 함, 분포만 출력")
    args = ap.parse_args()

    return run(
        db_path=resolve_db_path(args.db),
        render_url=resolve_render_url(args.render_url),
        admin_key=resolve_admin_key(args.admin_key),
        source_filter=args.source,
        batch_size=args.batch_size,
        timeout=args.timeout,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
