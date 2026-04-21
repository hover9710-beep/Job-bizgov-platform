# -*- coding: utf-8 -*-
"""Flask 목록/상세 source·파서 검증 로그 (FLASK_AUDIT_UI=1 일 때만)."""
from __future__ import annotations

import os
import sqlite3
from typing import Any


def audit_ui_enabled() -> bool:
    v = os.environ.get("FLASK_AUDIT_UI", "").strip().lower()
    return v in ("1", "true", "yes", "on")


def log_source_mismatch_and_parser(
    rows_ui: list[dict],
    *,
    label: str,
    list_limit: int = 10,
) -> tuple[int, list[dict]]:
    """
    [A] db_source_snapshot vs final source
    [B] parser route + receipt 표시
    """
    from pipeline.presenter import extract_receipt_period, receipt_parser_label

    print(f"\n[audit-ui][A][B] {label}", flush=True)
    mismatch = 0
    exceptions: list[dict] = []
    for i, r in enumerate(rows_ui):
        sid = r.get("id")
        db_s = str(r.get("db_source_snapshot") or "").strip().lower()
        fin = str(r.get("source") or "").strip().lower()
        sb = r.get("source_badge") or ""
        t = (r.get("title") or "")[:60]
        if db_s and db_s != fin:
            mismatch += 1
            if len(exceptions) < 5:
                exceptions.append(
                    {"id": sid, "db_source_snapshot": db_s, "final_source": fin, "title": t}
                )
            print(
                f"  [!] id={sid} DB_snap={db_s!r} != final={fin!r} badge={sb!r} title={t!r}",
                flush=True,
            )
        if i < list_limit:
            pl = receipt_parser_label(r)
            rs, re_ = extract_receipt_period(r)
            print(
                f"  id={sid} src={fin!r} parser={pl} receipt={rs}~{re_} badge={sb!r} title={t[:40]!r}",
                flush=True,
            )
    if not mismatch:
        print("  [OK] db_source_snapshot == final (snapshot이 있을 때)", flush=True)
    print(f"  [요약] mismatch={mismatch}건", flush=True)
    return mismatch, exceptions


def log_detail_consistency(
    conn: sqlite3.Connection,
    pid: int,
    *,
    prepare_row: Any,
    normalize_item: Any,
) -> None:
    """[C] prepare+normalize 한 경로 기준 필드 덤프."""
    from pipeline.presenter import extract_receipt_period

    row = conn.execute(
        """
        SELECT id, title, organization, ministry, executing_agency, source, start_date, end_date,
               status, url, description, ai_result, pdf_path,
               receipt_start, receipt_end, biz_start, biz_end, raw_status, attachments_json
        FROM biz_projects
        WHERE id = ?
        """,
        (pid,),
    ).fetchone()
    if row is None:
        print(f"[audit-ui][C] id={pid} 없음", flush=True)
        return
    d = prepare_row(row)
    ui = normalize_item(d)
    desc = str(ui.get("description") or "")
    atts = ui.get("attachments_list") or []
    rs, re_ = extract_receipt_period(ui)
    print(
        f"[audit-ui][C] id={pid} source={ui.get('source')!r} status={ui.get('display_status')!r} "
        f"receipt={rs}~{re_} desc_len={len(desc)} attach_n={len(atts)}",
        flush=True,
    )


def run_detail_pair_audit(
    conn: sqlite3.Connection,
    pids: list[int],
    *,
    prepare_row: Any,
    normalize_item: Any,
) -> None:
    print("\n[audit-ui][C] detail·project 동일 전처리 (prepare→normalize)", flush=True)
    for pid in pids[:5]:
        log_detail_consistency(
            conn, pid, prepare_row=prepare_row, normalize_item=normalize_item
        )
