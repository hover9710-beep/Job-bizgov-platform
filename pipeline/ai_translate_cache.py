# AI 친화 통역 캐시 — biz_projects 의 ai_friendly_title + ai_friendly_summary 채움.
# ai_summary_cache.py 패턴 1:1 복제 (백로그 066 Phase 2-Alpha).

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

DEFAULT_LIMIT = int(os.environ.get("AI_TRANSLATE_LIMIT", "100"))

from pipeline.ai_translate import generate_project_friendly, load_attachment_text
from pipeline.mail_view import DB_PATH


def _norm_filter_arg(val: Optional[str]) -> Optional[str]:
    if val is None:
        return None
    t = str(val).strip()
    return t if t else None


def load_candidates(
    source: Optional[str] = None,
    status: Optional[str] = None,
    end_date_from: Optional[str] = None,
    only_visible: bool = True,
) -> List[Dict[str, Any]]:
    """위젯에 노출 가능성 있는 행 우선 (start_date >= 2026-01-01). filter 인자 ai_summary_cache 와 동일."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        query = "SELECT * FROM biz_projects WHERE 1=1"
        params: List[Any] = []
        if only_visible:
            query += " AND COALESCE(start_date, '') >= '2026-01-01'"
        if source:
            query += " AND source = ?"
            params.append(source)
        if status:
            query += " AND status = ?"
            params.append(status)
        if end_date_from:
            query += (
                " AND end_date IS NOT NULL AND TRIM(end_date) != '' "
                "AND end_date >= ?"
            )
            params.append(end_date_from)
        query += " ORDER BY COALESCE(notice_order, 0) DESC, id DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _source_text_for_item(item: Dict[str, Any]) -> str:
    """첨부 텍스트 → description → title+organization (각 최대 3000자)."""
    attachments_json = item.get("attachments_json") or ""
    if attachments_json and isinstance(attachments_json, str):
        try:
            import json as _json
            atts = _json.loads(attachments_json)
            if isinstance(atts, list) and atts:
                first = atts[0]
                name = first.get("filename") if isinstance(first, dict) else None
                if name:
                    att = load_attachment_text(
                        str(item.get("source") or ""), str(name)
                    )
                    if att.strip():
                        return att[:3000]
        except Exception:
            pass
    desc = str(item.get("description") or "").strip()
    if desc:
        return desc[:3000]
    title = str(item.get("title") or "").strip()
    org = str(item.get("organization") or "").strip()
    return f"{title}\n{org}".strip()[:3000]


def run_ai_translate_cache(
    *,
    limit: int,
    dry_run: bool,
    overwrite: bool,
    source: Optional[str] = None,
    status: Optional[str] = None,
    end_date_from: Optional[str] = None,
) -> int:
    if not dry_run and not os.environ.get("OPENAI_API_KEY", "").strip():
        print("[ai-translate] OPENAI_API_KEY 없음, skip", flush=True)
        return 0

    candidates = load_candidates(
        source=source, status=status, end_date_from=end_date_from
    )
    need_list = [
        c
        for c in candidates
        if overwrite or not str(c.get("ai_friendly_title") or "").strip()
    ]
    missing_n = len(need_list)

    extra = ""
    if source or status or end_date_from:
        extra = (
            f" source={source!r} status={status!r} end_date_from={end_date_from!r}"
        )
    print(
        f"[ai-translate] target={len(candidates)} missing={missing_n} limit={limit}{extra}",
        flush=True,
    )

    generated = skipped = failed = 0
    attempts = 0

    if dry_run:
        for c in need_list[:limit]:
            print(f"[ai-translate] DRY would translate id={c.get('id')} title={c.get('title')[:50]!r}", flush=True)
        print(
            f"[ai-translate] DONE generated=0 skipped=0 failed=0 (dry-run) would_translate={min(limit, missing_n)}",
            flush=True,
        )
        return 0

    conn = sqlite3.connect(str(DB_PATH))
    try:
        for c in candidates:
            iid = c.get("id")
            if iid is None:
                continue
            has = bool(str(c.get("ai_friendly_title") or "").strip())
            if has and not overwrite:
                skipped += 1
                continue
            if attempts >= limit:
                break
            attempts += 1

            text = _source_text_for_item(c)
            result = generate_project_friendly(c, text=text)
            if not result:
                print(f"[ai-translate] FAIL id={iid} (empty or error)", flush=True)
                failed += 1
                continue

            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            ft = result.get("friendly_title") or ""
            fs = result.get("friendly_summary") or ""
            conn.execute(
                """
                UPDATE biz_projects
                SET ai_friendly_title = ?, ai_friendly_summary = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (ft, fs, int(iid)),
            )
            print(
                f"[ai-translate] OK id={iid} title={ft!r} summary={fs!r}",
                flush=True,
            )
            generated += 1
        conn.commit()
    finally:
        conn.close()

    print(
        f"[ai-translate] DONE generated={generated} skipped={skipped} failed={failed}",
        flush=True,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="biz_projects 친화 통역 캐시 (백로그 066)")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=f"GPT 호출 상한 (기본: env AI_TRANSLATE_LIMIT 또는 {DEFAULT_LIMIT})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="DB/GPT 없이 대상만 로그",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="이미 ai_friendly_title 있어도 재통역",
    )
    parser.add_argument("--source", default=None)
    parser.add_argument("--status", default=None)
    parser.add_argument(
        "--end-date-from",
        default=None,
        metavar="DATE",
        help="end_date >= DATE (YYYY-MM-DD).",
    )
    args = parser.parse_args()
    lim = args.limit if args.limit is not None else DEFAULT_LIMIT
    if lim < 0:
        lim = 0
    src = _norm_filter_arg(args.source)
    st = _norm_filter_arg(args.status)
    edf = _norm_filter_arg(args.end_date_from)
    return run_ai_translate_cache(
        limit=lim,
        dry_run=args.dry_run,
        overwrite=args.overwrite,
        source=src,
        status=st,
        end_date_from=edf,
    )


if __name__ == "__main__":
    raise SystemExit(main())
