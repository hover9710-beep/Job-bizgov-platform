# -*- coding: utf-8 -*-
"""전북테크노파크 유관기관 공고 목록 수집 → biz_projects 저장."""
from __future__ import annotations

import os
import re
import sqlite3
import time

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

BASE_LIST = (
    "https://www.jbtp.or.kr/board/list.jbtp?"
    "boardId=BBS_0000007&listRow=10&listCel=1&menuCd=DOM_000000102002000000"
    "&paging=ok&startPage={page}"
)
MAX_PAGES = 7
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

DB_PATH = os.path.join(_ROOT, "db", "biz.db")
DEBUG_DIR = os.path.join(_ROOT, "data", "jbtp_related", "debug")

_DEFAULT_ORG = "전북테크노파크 유관기관"

_SESSION = requests.Session()
_SESSION.headers.update(HEADERS)
_SESSION.verify = False

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _debug_save(name: str, html: str) -> None:
    os.makedirs(DEBUG_DIR, exist_ok=True)
    path = os.path.join(DEBUG_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


def _parse_row_end_date(row) -> str:
    t_date = row.select_one("td.t_date")
    if t_date:
        m = _DATE_RE.search(t_date.get_text(" ", strip=True))
        if m:
            return m.group(1)
    row_text = row.get_text(" ", strip=True)
    dates = _DATE_RE.findall(row_text)
    return dates[0] if dates else ""


def _organization_from_title(title: str) -> str:
    m = re.match(r"\[(.+?)\]", (title or "").strip())
    return m.group(1).strip() if m else _DEFAULT_ORG


def parse_list_page(html: str, page_no: int) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("table tbody tr")
    out: list[dict] = []
    for row in rows:
        a = row.select_one("td.txt_left a") or row.select_one("a")
        if not a:
            continue
        title = a.get_text(strip=True)
        if not title:
            continue
        href = (a.get("href") or "").strip()
        m = re.search(r"dataSid=(\d+)", href)
        if not m:
            continue
        data_sid = m.group(1)
        detail_url = (
            "https://www.jbtp.or.kr/board/view.jbtp?"
            "menuCd=DOM_000000102002000000&boardId=BBS_0000007&dataSid=%s" % data_sid
        )
        end_date = _parse_row_end_date(row)
        out.append(
            {
                "title": title,
                "organization": _organization_from_title(title),
                "source": "jbtp_related",
                "site": "전북",
                "url": detail_url,
                "start_date": "",
                "end_date": end_date,
                "status": "확인 필요",
                "summary": "",
                "period_text": end_date,
            }
        )
    if not out:
        _debug_save("list_parse_fail_page_%s.html" % page_no, html)
    return out


def fetch_list_page(page_no: int) -> str:
    url = BASE_LIST.format(page=page_no)
    res = _SESSION.get(url, timeout=15)
    res.raise_for_status()
    return res.text


def collect_all_pages() -> list[dict]:
    by_url: dict[str, dict] = {}
    for page_no in range(1, MAX_PAGES + 1):
        try:
            html = fetch_list_page(page_no)
        except requests.RequestException as e:
            print("[JBTP유관] 목록 HTTP 실패 page=%s: %s" % (page_no, e))
            resp = getattr(e, "response", None)
            body = (resp.text if resp is not None else "") or ""
            if body:
                _debug_save("list_http_error_page_%s.html" % page_no, body)
            raise
        for item in parse_list_page(html, page_no):
            by_url[item["url"]] = item
        if page_no < MAX_PAGES:
            time.sleep(0.5)
    return list(by_url.values())


def save_to_db(results: list[dict]) -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    existing = {str(r[1]) for r in cur.execute("PRAGMA table_info(biz_projects)").fetchall()}
    want = [
        "title",
        "organization",
        "source",
        "site",
        "url",
        "start_date",
        "end_date",
        "status",
        "summary",
        "period_text",
    ]
    cols = [c for c in want if c in existing]
    if not cols:
        conn.close()
        raise RuntimeError("biz_projects 에서 INSERT 가능한 컬럼이 없습니다.")
    placeholders = ", ".join(["?"] * len(cols))
    col_sql = ", ".join(cols)
    sql = "INSERT OR IGNORE INTO biz_projects (%s) VALUES (%s)" % (col_sql, placeholders)
    for r in results:
        cur.execute(
            sql,
            tuple(r.get("site", "전북") if c == "site" else r[c] for c in cols),
        )
    conn.commit()
    conn.close()


def run() -> None:
    results = collect_all_pages()
    save_to_db(results)
    print("[JBTP유관] 완료: %d건" % len(results))


if __name__ == "__main__":
    run()
