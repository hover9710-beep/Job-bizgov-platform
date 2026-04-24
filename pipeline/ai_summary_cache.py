# 메일 대상 공고 중 ai_summary 없는 것만 GPT 호출 후 DB 저장.
# UI/mail_view에서 직접 호출하지 말 것.

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

DEFAULT_LIMIT = int(os.environ.get("AI_SUMMARY_LIMIT", "20"))

from pipeline.ai_summary import generate_project_summary, load_attachment_text
from pipeline.mail_view import (
    DB_PATH,
    URGENT_MAIL_DAYS,
    filter_ending_soon,
    filter_new,
    load_db_rows,
    to_mail_item,
    _today_str,
)


def _norm_filter_arg(val: Optional[str]) -> Optional[str]:
    if val is None:
        return None
    t = str(val).strip()
    return t if t else None


def load_by_filter(
    source: Optional[str] = None,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        query = "SELECT * FROM biz_projects WHERE 1=1"
        params: List[Any] = []
        if source:
            query += " AND source = ?"
            params.append(source)
        if status:
            query += " AND status = ?"
            params.append(status)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _source_text_for_item(mail_item: Dict[str, Any]) -> str:
    """첨부텍스트 → description → title+organization (각 최대 3000자)."""
    names = mail_item.get("attachment_names") or []
    if isinstance(names, list) and names:
        att = load_attachment_text(
            str(mail_item.get("source") or ""),
            str(names[0]),
        )
        if att.strip():
            return att[:3000]
    desc = str(mail_item.get("description") or "").strip()
    if desc:
        return desc[:3000]
    title = str(mail_item.get("title") or "").strip()
    org = str(mail_item.get("organization") or "").strip()
    return f"{title}\n{org}".strip()[:3000]


def _collect_mail_candidates(today: str) -> List[Dict[str, Any]]:
    rows = load_db_rows()
    items = [to_mail_item(r, today=today) for r in rows]
    new_l = filter_new(items, days=7, today=today)
    ur_l = filter_ending_soon(items, days=URGENT_MAIL_DAYS, today=today)
    seen: Set[Any] = set()
    out: List[Dict[str, Any]] = []
    for it in ur_l + new_l:
        iid = it.get("id")
        if iid is None or iid in seen:
            continue
        seen.add(iid)
        out.append(it)
    return out


def _collect_candidates(
    today: str,
    *,
    source: Optional[str],
    status: Optional[str],
) -> List[Dict[str, Any]]:
    if source or status:
        rows = load_by_filter(source=source, status=status)
        return [to_mail_item(r, today=today) for r in rows]
    return _collect_mail_candidates(today)


def run_ai_summary_cache(
    *,
    limit: int,
    dry_run: bool,
    overwrite: bool,
    source: Optional[str] = None,
    status: Optional[str] = None,
) -> int:
    if not dry_run and not os.environ.get("OPENAI_API_KEY", "").strip():
        print("[ai-summary] OPENAI_API_KEY 없음, skip", flush=True)
        return 0

    today = _today_str()
    candidates = _collect_candidates(today, source=source, status=status)
    need_list = [
        c
        for c in candidates
        if overwrite or not str(c.get("ai_summary") or "").strip()
    ]
    missing_n = len(need_list)

    extra = ""
    if source or status:
        extra = f" source={source!r} status={status!r}"
    print(
        f"[ai-summary] target={len(candidates)} missing={missing_n} limit={limit}{extra}",
        flush=True,
    )

    generated = skipped = failed = 0
    attempts = 0

    if dry_run:
        for it in candidates:
            iid = it.get("id")
            has = bool(str(it.get("ai_summary") or "").strip())
            if has and not overwrite:
                print(f"[ai-summary] SKIP id={iid} reason=already_exists", flush=True)
                skipped += 1
        for it in need_list[:limit]:
            print(f"[ai-summary] DRY would generate id={it.get('id')}", flush=True)
        print(
            f"[ai-summary] DONE generated=0 skipped={skipped} failed=0 (dry-run)",
            flush=True,
        )
        return 0

    conn = sqlite3.connect(str(DB_PATH))
    try:
        for it in candidates:
            iid = it.get("id")
            if iid is None:
                continue
            has = bool(str(it.get("ai_summary") or "").strip())
            if has and not overwrite:
                print(f"[ai-summary] SKIP id={iid} reason=already_exists", flush=True)
                skipped += 1
                continue
            if attempts >= limit:
                break
            attempts += 1

            text = _source_text_for_item(it)
            summary = generate_project_summary(it, text=text)
            if not summary:
                print(f"[ai-summary] FAIL id={iid} (empty or error)", flush=True)
                failed += 1
                continue

            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            conn.execute(
                """
                UPDATE biz_projects
                SET ai_summary = ?, ai_summary_at = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (summary, now, int(iid)),
            )
            print(
                f"[ai-summary] OK id={iid} chars={len(summary)}",
                flush=True,
            )
            generated += 1
        conn.commit()
    finally:
        conn.close()

    print(
        f"[ai-summary] DONE generated={generated} skipped={skipped} failed={failed}",
        flush=True,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="메일 후보 공고 AI 요약 캐시 (DB)")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=f"GPT 호출 상한 (기본: env AI_SUMMARY_LIMIT 또는 {DEFAULT_LIMIT})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="DB/GPT 없이 대상·SKIP 로그만",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="이미 ai_summary 있어도 재생성",
    )
    parser.add_argument("--source", default=None)
    parser.add_argument("--status", default=None)
    args = parser.parse_args()
    lim = args.limit if args.limit is not None else DEFAULT_LIMIT
    if lim < 0:
        lim = 0
    src = _norm_filter_arg(args.source)
    st = _norm_filter_arg(args.status)
    return run_ai_summary_cache(
        limit=lim,
        dry_run=args.dry_run,
        overwrite=args.overwrite,
        source=src,
        status=st,
    )


if __name__ == "__main__":
    raise SystemExit(main())
