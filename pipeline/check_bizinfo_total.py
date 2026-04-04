# -*- coding: utf-8 -*-
"""
기업마당 site 총건 vs JSON(bizinfo) vs DB(biz_projects source=bizinfo) 3-way 비교.

실행:
  py pipeline/check_bizinfo_total.py
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parent.parent
_PIPELINE = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_PIPELINE) not in sys.path:
    sys.path.insert(0, str(_PIPELINE))

import requests
from bs4 import BeautifulSoup
from reports.blueprints.connector_www_bizinfo_go_kr import LIST_API, LIST_PAGE_ROWS
from project_quality import infer_source

DB_PATH = _ROOT / "db" / "biz.db"
ALL_JSON_PATH = _ROOT / "data" / "all_jb" / "all_jb.json"


def _site_total_and_pages(session: requests.Session) -> Tuple[Optional[int], int]:
    """목록 페이지 순회로 총 건수·페이지 수. 실패 시 (None, 0)."""
    total = 0
    cpage = 1
    max_pages = 5000
    while cpage <= max_pages:
        try:
            r = session.get(
                LIST_API,
                params={"pageNo": 1, "rows": LIST_PAGE_ROWS, "cpage": cpage},
                timeout=25,
            )
            r.raise_for_status()
        except requests.RequestException:
            return None, 0
        soup = BeautifulSoup(r.text, "html.parser")
        rows = soup.select("table tbody tr")
        valid = 0
        for row in rows:
            tds = row.find_all("td")
            if len(tds) < 2:
                continue
            if row.find("a", href=True):
                valid += 1
        if valid == 0:
            break
        total += valid
        cpage += 1
    pages = cpage - 1 if cpage > 1 else 0
    # HTML에서 총건 텍스트 보조 파싱
    if total == 0:
        return None, 0
    return total, pages


def _fallback_total_from_first_page(html: str) -> Optional[int]:
    """총 N건 패턴."""
    for pat in [
        r"총\s*([\d,]+)\s*건",
        r"전체\s*([\d,]+)\s*건",
        r"total(?:Count|Records)?\s*[=:]\s*['\"]?(\d+)",
    ]:
        m = re.search(pat, html, re.I)
        if m:
            try:
                return int(m.group(1).replace(",", ""))
            except ValueError:
                continue
    return None


def _load_json_items() -> List[Dict[str, Any]]:
    if not ALL_JSON_PATH.exists():
        return []
    try:
        data = json.loads(ALL_JSON_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, dict)]


def _count_bizinfo_in_json(items: List[Dict[str, Any]]) -> int:
    n = 0
    for it in items:
        url = str(it.get("url") or "")
        site = str(it.get("site") or "")
        src = infer_source(
            url,
            site,
            str(it.get("source") or ""),
            organization=str(it.get("organization") or ""),
            title=str(it.get("title") or ""),
        )
        if src == "bizinfo":
            n += 1
    return n


def _count_bizinfo_in_db(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) FROM biz_projects
        WHERE LOWER(TRIM(COALESCE(source,''))) = 'bizinfo'
        """
    ).fetchone()
    return int(row[0]) if row else 0


def _result_label(site_total: Optional[int], json_n: int, db_n: int) -> str:
    if site_total is None or site_total <= 0:
        return "UNKNOWN"
    rate = db_n / site_total if site_total else 0.0
    if rate >= 0.95:
        return "FULL"
    if rate >= 0.10:
        return "PARTIAL"
    return "NOT FULL"


def main() -> int:
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass

    parser = argparse.ArgumentParser(description="기업마당 3-way 건수 점검")
    parser.add_argument("--db", type=Path, default=DB_PATH)
    args = parser.parse_args()
    db_path = args.db.resolve()

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "ko-KR,ko;q=0.9",
        }
    )

    site_total, pages = _site_total_and_pages(session)
    if site_total is None:
        try:
            r = session.get(
                LIST_API,
                params={"pageNo": 1, "rows": LIST_PAGE_ROWS, "cpage": 1},
                timeout=25,
            )
            fb = _fallback_total_from_first_page(r.text)
            if fb:
                site_total = fb
        except requests.RequestException:
            pass

    items = _load_json_items()
    json_n = _count_bizinfo_in_json(items)
    merged_n = len(items)

    db_n = 0
    if db_path.exists():
        conn = sqlite3.connect(db_path)
        try:
            db_n = _count_bizinfo_in_db(conn)
        finally:
            conn.close()

    st = site_total if site_total is not None else 0
    missing = max(0, st - db_n) if site_total is not None else 0
    rate_pct = (db_n / st * 100) if st else 0.0
    label = _result_label(site_total, json_n, db_n)

    print("[bizinfo total check]")
    print(f"site total: {site_total if site_total is not None else 'UNKNOWN'}")
    print(f"site pages: {pages}")
    print(f"merged (all_jb.json): {merged_n}")
    print(f"collected (JSON): {json_n}")
    print(f"collected (DB): {db_n}")
    print(
        "note: JSON은 병합 파일만 집계, DB는 biz_projects 전체 중 source=bizinfo "
        "(과거·중복 행 포함 가능). 수치가 다르면 정상일 수 있습니다."
    )
    print(f"missing: {missing}")
    print(f"collect rate: {rate_pct:.1f}%")
    print(f"result: {label}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
