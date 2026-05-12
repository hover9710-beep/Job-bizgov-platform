# -*- coding: utf-8 -*-
"""커넥터 공통 유틸. 새 기관 커넥터 작성 시 import해서 사용."""
from __future__ import annotations

import os
import re
import sqlite3
import time
from typing import Callable

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
)
DEFAULT_DB_PATH = os.path.join(_ROOT, "db", "biz.db")
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)

PERIOD_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})")
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def make_session(extra_headers: dict | None = None) -> requests.Session:
    """기본 세션 (UA, verify=False, urllib3 경고 무시)."""
    s = requests.Session()
    headers = {"User-Agent": DEFAULT_UA}
    if extra_headers:
        headers.update(extra_headers)
    s.headers.update(headers)
    s.verify = False
    return s


def debug_save(connector_name: str, filename: str, html: str) -> None:
    """data/{connector}/debug/ 폴더에 HTML 저장."""
    debug_dir = os.path.join(_ROOT, "data", connector_name, "debug")
    os.makedirs(debug_dir, exist_ok=True)
    with open(os.path.join(debug_dir, filename), "w", encoding="utf-8") as f:
        f.write(html)


def parse_period(text: str) -> tuple[str, str]:
    """'2026-04-30 ~ 2026-05-11' → ('2026-04-30', '2026-05-11')."""
    m = PERIOD_RE.search(text or "")
    return (m.group(1), m.group(2)) if m else ("", "")


def normalize_status(raw: str) -> str:
    """원본 상태 문자열 → '접수중' / '마감' / '' 정규화."""
    if not raw:
        return ""
    if "진행중" in raw or "접수중" in raw or "접수" in raw:
        return "접수중"
    if "마감" in raw or "종료" in raw:
        return "마감"
    return ""


def save_to_db(
    rows: list[dict],
    source_name: str,
    db_path: str = DEFAULT_DB_PATH,
) -> int:
    """
    biz_projects INSERT OR IGNORE.
    - URL UNIQUE 가정 → 중복 자동 차단
    - dict 키 중 실제 컬럼만 INSERT (PRAGMA table_info 기반)
    - 반환: 신규 INSERT 건수
    """
    if not rows:
        return 0

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    existing = {
        str(r[1])
        for r in cur.execute("PRAGMA table_info(biz_projects)").fetchall()
    }

    candidate_cols = list(rows[0].keys())
    cols = [c for c in candidate_cols if c in existing]
    if not cols:
        conn.close()
        raise RuntimeError(
            f"[{source_name}] biz_projects에 INSERT 가능한 컬럼이 없습니다."
        )

    placeholders = ", ".join(["?"] * len(cols))
    col_sql = ", ".join(cols)
    sql = f"INSERT OR IGNORE INTO biz_projects ({col_sql}) VALUES ({placeholders})"

    inserted = 0
    for r in rows:
        cur.execute(sql, tuple(r.get(c, "") for c in cols))
        inserted += cur.rowcount
    conn.commit()
    conn.close()

    print(
        f"[{source_name}] DB 저장: 시도 {len(rows)}건, "
        f"신규 {inserted}건 (중복 {len(rows) - inserted}건)"
    )
    return inserted


def paginate(
    fetch_fn: Callable[[int], str],
    parse_fn: Callable[[str, int], list[dict]],
    source_name: str,
    max_pages: int = 30,
    sleep: float = 0.5,
    key: str = "url",
) -> list[dict]:
    """
    페이지 순회 골격.
    - fetch_fn(page) → HTML
    - parse_fn(html, page) → list[dict]
    - 신규 0건이면 자동 종료
    """
    by_key: dict[str, dict] = {}
    for page_no in range(1, max_pages + 1):
        try:
            html = fetch_fn(page_no)
        except requests.RequestException as e:
            print(f"[{source_name}] HTTP 실패 page={page_no}: {e}")
            resp = getattr(e, "response", None)
            body = (resp.text if resp is not None else "") or ""
            if body:
                debug_save(source_name, f"http_error_p{page_no}.html", body)
            raise

        items = parse_fn(html, page_no)
        if not items:
            print(f"[{source_name}] page {page_no}: 0건 → 종료")
            break

        new_count = sum(1 for it in items if it.get(key) not in by_key)
        for it in items:
            k = it.get(key)
            if k:
                by_key[k] = it

        print(
            f"[{source_name}] page {page_no:2d}: "
            f"{len(items)}건 (신규 {new_count}건)"
        )

        if new_count == 0:
            print(f"[{source_name}] 신규 없음 → 종료")
            break

        if page_no < max_pages:
            time.sleep(sleep)

    return list(by_key.values())
