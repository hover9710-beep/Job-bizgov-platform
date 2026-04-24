# 공고 자체 라벨링 모듈.
# GPT가 공고를 보고 어떤 회사에 맞는지 라벨을 붙인다.
# UI/mail에서 직접 호출하지 말 것.

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set

from openai import OpenAI

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

LABEL_LIST = [
    "수출기업",
    "제조업",
    "스타트업",
    "R&D",
    "전북지역",
    "중소기업",
]

DEFAULT_LIMIT = int(os.environ.get("RECOMMEND_LABEL_LIMIT", 50))

from pipeline import update_db as _update_db_mod
from pipeline.mail_view import (
    DB_PATH,
    URGENT_MAIL_DAYS,
    filter_ending_soon,
    filter_new,
    to_mail_item,
    _today_str,
)
from pipeline.ui_view import load_db_rows


def _ensure_recommend_label_columns(conn: sqlite3.Connection) -> None:
    if _update_db_mod._table_exists(conn, "biz_projects"):
        _update_db_mod._ensure_column(conn, "biz_projects", "recommend_label", "TEXT")
        _update_db_mod._ensure_column(conn, "biz_projects", "recommend_label_at", "TEXT")

_SYSTEM_PROMPT = (
    "아래 정부지원사업 공고를 보고 가장 적합한 라벨을 골라라.\n"
    "   라벨 목록: 수출기업, 제조업, 스타트업, R&D, 전북지역, 중소기업\n"
    "   반드시 목록 중에서 1~2개만 골라 쉼표로 구분해서 답해라. 다른 말은 하지 말 것."
)


def _row_to_mail_item(row: Dict[str, Any], today: str) -> Dict[str, Any]:
    it = to_mail_item(row, today=today)
    it["recommend_label"] = str(row.get("recommend_label") or "").strip()
    return it


def _collect_candidates(today: str) -> List[Dict[str, Any]]:
    rows = load_db_rows()
    items = [_row_to_mail_item(r, today) for r in rows]
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


def _generate_recommend_label(title: str, organization: str, description: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return ""
    desc = str(description or "")[:500]
    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"공고명: {title}\n기관: {organization}\n내용: {desc}",
                },
            ],
            max_tokens=60,
            temperature=0.2,
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"[recommend] GPT 실패: {e}", flush=True)
        return ""


def run_recommend_label(
    *,
    limit: int,
    dry_run: bool,
    overwrite: bool,
) -> int:
    if not dry_run and not os.environ.get("OPENAI_API_KEY", "").strip():
        print("[recommend] OPENAI_API_KEY 없음, skip", flush=True)
        return 0

    today = _today_str()
    candidates = _collect_candidates(today)
    need_list = [
        c
        for c in candidates
        if overwrite or not str(c.get("recommend_label") or "").strip()
    ]
    missing_n = len(need_list)

    print(
        f"[recommend] target={len(candidates)} missing={missing_n} limit={limit}",
        flush=True,
    )

    generated = skipped = failed = 0
    attempts = 0

    if dry_run:
        for it in candidates:
            iid = it.get("id")
            has = bool(str(it.get("recommend_label") or "").strip())
            if has and not overwrite:
                print(f"[recommend] SKIP id={iid} reason=already_exists", flush=True)
                skipped += 1
        for it in need_list[:limit]:
            print(f"[recommend] DRY would generate id={it.get('id')}", flush=True)
        print(
            f"[recommend] DONE generated=0 skipped={skipped} failed=0 (dry-run)",
            flush=True,
        )
        return 0

    conn = sqlite3.connect(str(DB_PATH))
    try:
        _ensure_recommend_label_columns(conn)
        for it in candidates:
            iid = it.get("id")
            if iid is None:
                continue
            has = bool(str(it.get("recommend_label") or "").strip())
            if has and not overwrite:
                print(f"[recommend] SKIP id={iid} reason=already_exists", flush=True)
                skipped += 1
                continue
            if attempts >= limit:
                break
            attempts += 1

            title = str(it.get("title") or "").strip()
            org = str(it.get("organization") or "").strip()
            desc = str(it.get("description") or "").strip()
            label = _generate_recommend_label(title, org, desc)
            if not label:
                print(f"[recommend] FAIL id={iid} (empty or error)", flush=True)
                failed += 1
                continue

            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            conn.execute(
                """
                UPDATE biz_projects
                SET recommend_label = ?, recommend_label_at = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (label, now, int(iid)),
            )
            print(f"[recommend] OK id={iid} label={label}", flush=True)
            generated += 1
        conn.commit()
    finally:
        conn.close()

    print(
        f"[recommend] DONE generated={generated} skipped={skipped} failed={failed}",
        flush=True,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="메일 후보 공고 추천 라벨 (DB)")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            f"GPT 호출 상한 (기본: env RECOMMEND_LABEL_LIMIT 또는 {DEFAULT_LIMIT})"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="DB/GPT 없이 대상·SKIP 로그만",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="이미 recommend_label 있어도 재생성",
    )
    args = parser.parse_args()
    lim = args.limit if args.limit is not None else DEFAULT_LIMIT
    if lim < 0:
        lim = 0
    return run_recommend_label(limit=lim, dry_run=args.dry_run, overwrite=args.overwrite)


if __name__ == "__main__":
    raise SystemExit(main())
