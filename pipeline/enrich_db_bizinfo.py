# -*- coding: utf-8 -*-
"""
DB 기반 bizinfo 상세 보강 (one-time backfill).

status='확인 필요' + period_text 빈값 + url 보유 인 bizinfo 행을, url 로 직접
fetch_detail 해 period_text / start_date / end_date / status 를 DB 에 UPDATE.

connector_bizinfo --enrich-detail (JSON 기반) 이 닿지 못하는, 현재 크롤본
(bizinfo_all.json) 밖 '과거 누적' 행 복구용.
백로그: docs/backlog/unknown_empty_period_text.md

실행 (프로젝트 루트):
  py pipeline/enrich_db_bizinfo.py --dry-run --limit 10   # 검증
  py pipeline/enrich_db_bizinfo.py --limit 100            # 일부만
  py pipeline/enrich_db_bizinfo.py                        # 본 실행

멱등: period_text·status 가 갱신되면 대상 쿼리에서 빠지므로 재실행 안전.
DB 변경 — 실행 전 db/biz.db 백업 권장.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_PIPELINE = ROOT / "pipeline"
if str(_PIPELINE) not in sys.path:
    sys.path.insert(0, str(_PIPELINE))

from connectors.connector_bizinfo import fetch_detail
from reports.blueprints.connector_www_bizinfo_go_kr import HEADERS, build_session
from pipeline.bizinfo_dates import parse_bizinfo_dates
from normalize_project import infer_status
from db_path import resolve_db_path

# enrich 누락 대상: bizinfo + 확인 필요 + period_text 빈값 + url 보유.
TARGET_SQL = """
    SELECT id, title, url, start_date, description
    FROM biz_projects
    WHERE source = 'bizinfo'
      AND status = '확인 필요'
      AND (period_text IS NULL OR TRIM(period_text) = '')
      AND url IS NOT NULL AND TRIM(url) != ''
    ORDER BY id
"""


def _utf8_stdio() -> None:
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass


def run(
    *,
    dry_run: bool = False,
    limit: Optional[int] = None,
    delay_sec: float = 0.12,
    verify_ssl: bool = True,
) -> Dict[str, Any]:
    _utf8_stdio()
    db_path = resolve_db_path()
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(TARGET_SQL).fetchall()
    if limit is not None:
        rows = rows[: int(limit)]
    n = len(rows)
    print(f"[enrich-db] sqlite={db_path}", flush=True)
    print(f"[enrich-db] 대상 {n}건 (dry_run={dry_run})", flush=True)
    if n == 0:
        conn.close()
        return {"target": 0, "updated": 0, "fetch_fail": 0, "status_dist": {}}

    session = build_session(verify=verify_ssl)
    session.headers.update(HEADERS)
    today = date.today().isoformat()

    updated = 0
    fetch_fail = 0
    status_dist: Dict[str, int] = {}
    for i, (rid, title, url, sd0, desc0) in enumerate(rows, 1):
        try:
            detail = fetch_detail(str(url), session)
        except Exception as exc:
            print(f"[enrich-db] id={rid} fetch 예외: {str(exc)[:100]}", flush=True)
            fetch_fail += 1
            time.sleep(delay_sec)
            continue
        if not detail:
            fetch_fail += 1
            time.sleep(delay_sec)
            continue

        # run_enrich_detail_from_file 과 동일한 날짜 머지 규약.
        desc = str(detail.get("body") or desc0 or "").strip()
        application_period = str(detail.get("period") or "").strip()
        label_map = dict(detail.get("period_label_map") or {})
        merged: Dict[str, Any] = {
            "title": str(detail.get("title") or title or ""),
            "description": desc,
            "body": desc,
            "date": str(sd0 or ""),
            "period": application_period,
        }
        merged.update(label_map)
        dates = parse_bizinfo_dates(merged)

        new_pt = dates.get("period_text") or application_period
        new_sd = dates.get("start_date") or str(sd0 or "")
        new_ed = dates.get("end_date") or ""
        new_status = infer_status(new_pt, new_sd, new_ed, today)
        status_dist[new_status] = status_dist.get(new_status, 0) + 1

        if dry_run:
            print(
                f"[{i}/{n}] id={rid} period={new_pt[:42]!r} "
                f"end={new_ed!r} -> {new_status}",
                flush=True,
            )
        else:
            conn.execute(
                "UPDATE biz_projects SET period_text = ?, start_date = ?, "
                "end_date = ?, status = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (new_pt, new_sd, new_ed, new_status, int(rid)),
            )
            updated += 1
            if updated % 50 == 0:
                conn.commit()
                print(f"[enrich-db] 진행 {i}/{n} (updated={updated})", flush=True)
        time.sleep(delay_sec)

    if not dry_run:
        conn.commit()
    conn.close()

    tail = "(dry-run, UPDATE 안 함)" if dry_run else f"updated {updated}"
    print(
        f"[enrich-db] 완료 — 대상 {n}, {tail}, fetch 실패 {fetch_fail}",
        flush=True,
    )
    print(f"[enrich-db] 산출 status 분포: {status_dist}", flush=True)
    return {
        "target": n,
        "updated": updated,
        "fetch_fail": fetch_fail,
        "status_dist": status_dist,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="DB 기반 bizinfo 상세 보강 (백필)")
    parser.add_argument(
        "--dry-run", action="store_true", help="fetch·계산만, DB UPDATE 안 함"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="처리 건수 제한 (테스트용)"
    )
    parser.add_argument(
        "--no-verify-ssl", action="store_true", help="SSL 검증 끄기"
    )
    args = parser.parse_args()
    run(dry_run=args.dry_run, limit=args.limit, verify_ssl=not args.no_verify_ssl)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
