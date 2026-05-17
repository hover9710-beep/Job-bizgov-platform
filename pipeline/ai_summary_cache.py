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

DEFAULT_LIMIT = int(os.environ.get("AI_SUMMARY_LIMIT", "200"))

from pipeline.ai_summary import (
    batch_generate_summary,
    generate_project_summary,
    load_attachment_text,
)
from pipeline.mail_view import (
    DB_PATH,
    URGENT_MAIL_DAYS,
    filter_ending_soon,
    filter_new,
    load_db_rows,
    to_mail_item,
    _today_str,
)

BATCH_SIZE = 10  # 1회 GPT 호출당 요약 행 수 (백로그 069 Phase 2, b066 사이클 2 검증된 패턴)
COMMIT_INTERVAL = 50  # N 행마다 conn.commit (중간 중단 시 손실 한도)


def _norm_filter_arg(val: Optional[str]) -> Optional[str]:
    if val is None:
        return None
    t = str(val).strip()
    return t if t else None


def load_by_filter(
    source: Optional[str] = None,
    status: Optional[str] = None,
    end_date_from: Optional[str] = None,
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
        if end_date_from:
            query += (
                " AND end_date IS NOT NULL AND TRIM(end_date) != '' "
                "AND end_date >= ?"
            )
            params.append(end_date_from)
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
    end_date_from: Optional[str],
) -> List[Dict[str, Any]]:
    if source or status or end_date_from:
        rows = load_by_filter(
            source=source,
            status=status,
            end_date_from=end_date_from,
        )
        return [to_mail_item(r, today=today) for r in rows]
    return _collect_mail_candidates(today)


def _collect_widget_targets(
    today: str,
    *,
    source: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """위젯 노출 대상 (start_date >= 2026-01-01) 만 — Phase 2 보강용 (백로그 069)."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        query = (
            "SELECT * FROM biz_projects "
            "WHERE COALESCE(start_date, '') >= '2026-01-01'"
        )
        params: List[Any] = []
        if source:
            query += " AND source = ?"
            params.append(source)
        query += " ORDER BY COALESCE(notice_order, 0) DESC, id DESC"
        rows = conn.execute(query, params).fetchall()
        return [to_mail_item(dict(r), today=today) for r in rows]
    finally:
        conn.close()


def run_ai_summary_cache(
    *,
    limit: int,
    dry_run: bool,
    overwrite: bool,
    source: Optional[str] = None,
    status: Optional[str] = None,
    end_date_from: Optional[str] = None,
    widget_targets: bool = False,
) -> int:
    if not dry_run and not os.environ.get("OPENAI_API_KEY", "").strip():
        print("[ai-summary] OPENAI_API_KEY 없음, skip", flush=True)
        return 0

    today = _today_str()
    if widget_targets:
        candidates = _collect_widget_targets(today, source=source)
    else:
        candidates = _collect_candidates(
            today,
            source=source,
            status=status,
            end_date_from=end_date_from,
        )

    pending: List[Dict[str, Any]] = []
    skipped = 0
    for c in candidates:
        iid = c.get("id")
        if iid is None:
            continue
        has = bool(str(c.get("ai_summary") or "").strip())
        if has and not overwrite:
            skipped += 1
            continue
        pending.append(c)
        if len(pending) >= limit:
            break

    extra = ""
    if widget_targets:
        extra = f" widget_targets=True source={source!r}"
    elif source or status or end_date_from:
        extra = f" source={source!r} status={status!r} end_date_from={end_date_from!r}"
    print(
        f"[ai-summary] target={len(candidates)} pending={len(pending)} "
        f"skipped={skipped} limit={limit}{extra}",
        flush=True,
    )
    print(
        f"[ai-summary] batch mode: BATCH_SIZE={BATCH_SIZE} COMMIT_INTERVAL={COMMIT_INTERVAL}",
        flush=True,
    )

    if dry_run:
        for c in pending[: min(limit, 10)]:
            print(
                f"[ai-summary] DRY would generate id={c.get('id')} title={str(c.get('title'))[:50]!r}",
                flush=True,
            )
        print(
            f"[ai-summary] DONE generated=0 skipped={skipped} failed=0 (dry-run) "
            f"would_generate={len(pending)}",
            flush=True,
        )
        return 0

    generated = failed = 0
    conn = sqlite3.connect(str(DB_PATH))
    since_last_commit = 0
    try:
        for batch_start in range(0, len(pending), BATCH_SIZE):
            batch = pending[batch_start : batch_start + BATCH_SIZE]
            texts = [_source_text_for_item(b) for b in batch]
            results = batch_generate_summary(batch, texts)
            if not results:
                print(
                    f"[ai-summary] BATCH_FAIL start={batch_start} n={len(batch)} (전체 skip)",
                    flush=True,
                )
                failed += len(batch)
                continue

            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            batch_ok = 0
            for idx, item in enumerate(batch):
                summary = results.get(idx)
                if not summary:
                    failed += 1
                    continue
                conn.execute(
                    """
                    UPDATE biz_projects
                    SET ai_summary = ?, ai_summary_at = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (summary, now, int(item["id"])),
                )
                generated += 1
                batch_ok += 1
                since_last_commit += 1

            print(
                f"[ai-summary] BATCH ok={batch_ok}/{len(batch)} "
                f"progress={generated}/{len(pending)} "
                f"({100*generated/max(1,len(pending)):.1f}%)",
                flush=True,
            )

            if since_last_commit >= COMMIT_INTERVAL:
                conn.commit()
                since_last_commit = 0
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
    parser.add_argument(
        "--end-date-from",
        default=None,
        metavar="DATE",
        help="end_date >= DATE (YYYY-MM-DD). 'today' 는 오늘 날짜. --source 등과 조합.",
    )
    parser.add_argument(
        "--widget-targets",
        action="store_true",
        help="위젯 노출 대상 (start_date >= 2026-01-01) 만 처리 — Phase 2 보강용 (백로그 069).",
    )
    args = parser.parse_args()
    lim = args.limit if args.limit is not None else DEFAULT_LIMIT
    if lim < 0:
        lim = 0
    src = _norm_filter_arg(args.source)
    st = _norm_filter_arg(args.status)
    edf_raw = _norm_filter_arg(args.end_date_from)
    edf: Optional[str] = None
    if edf_raw is not None:
        edf = _today_str() if edf_raw.lower() == "today" else edf_raw
    return run_ai_summary_cache(
        limit=lim,
        dry_run=args.dry_run,
        overwrite=args.overwrite,
        source=src,
        status=st,
        end_date_from=edf,
        widget_targets=args.widget_targets,
    )


if __name__ == "__main__":
    raise SystemExit(main())
