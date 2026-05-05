# -*- coding: utf-8 -*-
"""
전북바이오융합산업진흥원(jif.re.kr) 일반공고 목록 수집 및 (레거시) 첨부 다운로드.

실행: py connectors/connector_jbbi.py
결과: data/jbbi/YYYY-MM-DD.json
디버그(실패 시): data/jbbi/debug/*.html
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DB_PATH = "db/biz.db"

BASE = "https://www.jif.re.kr"
BOARD_UUID = "53473d307cb77a53017cb7e09b8e0003"
MENU_UUID = "53473d307cb7118c017cb71940970029"
TIMEOUT = 30
DOWNLOAD_DIR = "jif_downloads"

DATA_DIR = os.path.join(_ROOT, "data", "jbbi")
DEBUG_DIR = os.path.join(_ROOT, "data", "jbbi", "debug")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)
SESSION.verify = False

_FN_FILEDOWN_RE = re.compile(
    r"fn_fileDown\s*\(\s*['\"](\d+)['\"]\s*,\s*['\"]([0-9a-fA-F]+)['\"]\s*\)",
    re.I,
)
_DOWNLOAD_HREF_RE = re.compile(
    r"pathNum=(\d+).*?fileUUID=([0-9a-fA-F]+)",
    re.I,
)

_FN_VIEW_RE = re.compile(
    r"fn_view\s*\(\s*['\"]([0-9a-fA-F]{8,})['\"]\s*\)",
    re.I,
)

_FN_PAGE_MV_RE = re.compile(
    r"fn_pageMv\s*\(\s*0\s*,\s*''\s*,\s*(\d+)\s*,\s*10\s*\)",
    re.I,
)


def _cell_text(td) -> str:
    return " ".join((td.get_text() or "").split())


def _split_period(period_raw: str) -> Tuple[str, str]:
    s = (period_raw or "").strip()
    if not s:
        return "", ""
    if "~" in s:
        a, b = [x.strip() for x in s.split("~", 1)]
        return a, b
    return s, ""


def build_view_url(board_article_uuid: str) -> str:
    from urllib.parse import urlencode

    q = {
        "boardUUID": BOARD_UUID,
        "menuUUID": MENU_UUID,
        "boardArticleUUID": board_article_uuid,
        "categoryGroup": "0",
        "page": "1",
        "rowCount": "10",
    }
    return "%s/board/view.do?%s" % (BASE, urlencode(q))


def _debug_dump_html(prefix: str, html: str) -> str:
    os.makedirs(DEBUG_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(DEBUG_DIR, "%s_%s.html" % (prefix, stamp))
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def fetch_list_page_raw(page: int) -> str:
    params = {
        "boardUUID": BOARD_UUID,
        "menuUUID": MENU_UUID,
        "page": str(page),
        "rowCount": "10",
    }
    r = SESSION.get(
        "%s/board/list.do" % BASE,
        params=params,
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.text


def discover_last_page(html: str) -> int:
    soup = BeautifulSoup(html, "html.parser")
    page_nums: list[int] = []
    for a in soup.find_all("a", href=True):
        m = re.search(r"page=(\d+)", a.get("href") or "")
        if m:
            page_nums.append(int(m.group(1)))
    for a in soup.find_all("a"):
        text = a.get_text(strip=True)
        if text.isdigit():
            page_nums.append(int(text))
    for x in _FN_PAGE_MV_RE.findall(html):
        page_nums.append(int(x))
    if page_nums:
        return max(page_nums)
    return 50


def _parse_list_row(tr) -> Optional[Dict[str, Any]]:
    a = tr.find("a", onclick=True)
    if not a:
        return None
    oc = a.get("onclick") or ""
    m = _FN_VIEW_RE.search(oc)
    if not m:
        return None
    article_uuid = m.group(1)
    title = (a.get_text() or "").strip()
    if not title:
        return None
    tds = tr.find_all("td")
    if not tds:
        return None
    title_td = a.find_parent("td")
    try:
        ti = tds.index(title_td)
    except ValueError:
        ti = -1

    status = ""
    period_raw = ""
    author = ""
    wdate = ""

    first_txt = _cell_text(tds[0])
    colspan = tds[0].get("colspan")
    notice_row = (
        str(colspan) == "2"
        or first_txt == "공지"
        or (ti == 1 and "공지" in first_txt)
    )

    if notice_row:
        status = "공지"
        if len(tds) > 2:
            period_raw = _cell_text(tds[2])
        if len(tds) > 4:
            author = _cell_text(tds[4])
        if len(tds) > 5:
            wdate = _cell_text(tds[5])
    elif ti >= 2 and len(tds) > 1:
        status = _cell_text(tds[1])
        if len(tds) > 3:
            period_raw = _cell_text(tds[3])
        if len(tds) > 5:
            author = _cell_text(tds[5])
        if len(tds) > 6:
            wdate = _cell_text(tds[6])
    else:
        if len(tds) > 3:
            period_raw = _cell_text(tds[min(3, len(tds) - 1)])
        if len(tds) > 5:
            author = _cell_text(tds[5])
        if len(tds) > 6:
            wdate = _cell_text(tds[6])

    start_d, end_d = _split_period(period_raw)
    return {
        "boardArticleUUID": article_uuid,
        "title": title,
        "status": status.strip(),
        "period_raw": period_raw,
        "start_date": start_d,
        "end_date": end_d,
        "posted_date": wdate,
        "author": author,
        "url": build_view_url(article_uuid),
    }


def parse_list_page(html: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    rows_out: List[Dict[str, Any]] = []
    for tr in soup.select("table tbody tr"):
        row = _parse_list_row(tr)
        if row:
            rows_out.append(row)
    return rows_out


def collect_list() -> List[Dict[str, Any]]:
    """목록 페이지(페이지네이션 전체)에서 공고 메타를 수집한다."""
    first_html = fetch_list_page_raw(1)
    if not first_html.strip():
        path = _debug_dump_html("list_empty_p1", first_html)
        raise RuntimeError("목록 1페이지 응답이 비었습니다. debug=%s" % path)

    last_page = discover_last_page(first_html)
    merged: Dict[str, Dict[str, Any]] = {}

    def ingest(html: str) -> None:
        for row in parse_list_page(html):
            uid = row["boardArticleUUID"]
            merged[uid] = row

    ingest(first_html)
    if not merged:
        path = _debug_dump_html("list_no_rows_p1", first_html)
        raise RuntimeError("목록 파싱 결과가 없습니다. debug=%s" % path)

    for page in range(2, last_page + 1):
        html = fetch_list_page_raw(page)
        ingest(html)

    org_name = "전북바이오융합산업진흥원"
    result: List[Dict[str, Any]] = []
    for row in merged.values():
        result.append(
            {
                "title": row["title"],
                "organization": org_name,
                "source": "jbbi",
                "region": "전북",
                "url": row["url"],
                "start_date": row.get("start_date") or "",
                "end_date": row.get("end_date") or "",
                "status": row.get("status") or "",
                "summary": "",
                "attachments": [],
            }
        )

    def _sort_key(item: Dict[str, Any]) -> Tuple:
        sd = item.get("start_date") or ""
        ed = item.get("end_date") or ""
        return (sd, ed, item.get("title") or "")

    result.sort(key=_sort_key, reverse=True)
    return result


def save_json(items: List[Dict[str, Any]], day: Optional[str] = None) -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    if not day:
        day = date.today().strftime("%Y-%m-%d")
    path = os.path.join(DATA_DIR, "%s.json" % day)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    return path


def save_to_db(results):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    for r in results:
        cur.execute("""
            INSERT OR IGNORE INTO biz_projects
            (title, organization, source, site, url, start_date, end_date, status, period_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            r.get("title", ""),
            r.get("organization", "전북바이오융합원"),
            r.get("source", "jbbi"),
            r.get("region", "전북"),
            r.get("url", ""),
            r.get("start_date", ""),
            r.get("end_date", ""),
            r.get("status", "확인 필요"),
            r.get("end_date", "")
        ))
    conn.commit()
    conn.close()
    print(f"[JBBI] DB 저장: {len(results)}건")


def run() -> str:
    try:
        items = collect_list()
        out = save_json(items)
        save_to_db(items)
        print("[jbbi] 수집 %d건 -> %s" % (len(items), out))
        return out
    except requests.RequestException as e:
        err_html = ""
        try:
            if hasattr(e, "response") and e.response is not None:
                err_html = e.response.text or ""
        except Exception:
            pass
        if err_html:
            _debug_dump_html("list_http_error", err_html)
        print("[jbbi] HTTP 오류: %s" % e, file=sys.stderr)
        raise
    except Exception as e:
        try:
            html = fetch_list_page_raw(1)
            _debug_dump_html("list_parse_fail", html)
        except Exception:
            pass
        print("[jbbi] 수집 실패: %s" % e, file=sys.stderr)
        raise


def get_detail(boardArticleUUID):
    params = {
        "boardUUID": BOARD_UUID,
        "menuUUID": MENU_UUID,
        "boardArticleUUID": boardArticleUUID,
        "categoryGroup": "0",
        "page": "1",
        "rowCount": "10",
    }
    r = SESSION.get(
        "%s/board/view.do" % BASE,
        params=params,
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.text


def parse_files(soup):
    """<a>의 onclick에서 fn_fileDown('pathNum','fileUUID') 파싱. 동일 사이트는 href만 있는 경우도 처리."""
    seen = set()
    out = []

    for a in soup.find_all("a", onclick=True):
        oc = a.get("onclick") or ""
        if "fn_fileDown" not in oc:
            continue
        m = _FN_FILEDOWN_RE.search(oc)
        if not m:
            continue
        path_num, file_uuid = m.group(1), m.group(2)
        key = (path_num, file_uuid)
        if key in seen:
            continue
        seen.add(key)
        name = (a.get_text() or "").strip()
        out.append(
            {"pathNum": path_num, "fileUUID": file_uuid, "filename": name}
        )

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "downloadFile.do" not in href:
            continue
        m = _DOWNLOAD_HREF_RE.search(href)
        if not m:
            continue
        path_num, file_uuid = m.group(1), m.group(2)
        key = (path_num, file_uuid)
        if key in seen:
            continue
        seen.add(key)
        name = (a.get_text() or "").strip()
        out.append(
            {"pathNum": path_num, "fileUUID": file_uuid, "filename": name}
        )

    return out


def download_file(pathNum, fileUUID, filename):
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    base = (filename or "").strip()
    if not base:
        base = "file_%s.dat" % fileUUID
    base = os.path.basename(base)
    for bad in '<>:"/\\|?*':
        base = base.replace(bad, "_")
    path = os.path.join(DOWNLOAD_DIR, base)

    url = "%s/downloadFile.do" % BASE
    params = {"pathNum": pathNum, "fileUUID": fileUUID}
    r = SESSION.get(url, params=params, timeout=TIMEOUT, stream=True)
    r.raise_for_status()

    with open(path, "wb") as f:
        for chunk in r.iter_content(chunk_size=65536):
            if chunk:
                f.write(chunk)
    return path


if __name__ == "__main__":
    argv = [a.strip().lower() for a in sys.argv[1:]]
    if argv and argv[0] in ("--download", "-d", "download"):
        board_article_uuid = input("boardArticleUUID: ").strip()
        if not board_article_uuid:
            print("boardArticleUUID가 비어 있습니다.")
            raise SystemExit(1)

        html = get_detail(board_article_uuid)
        soup = BeautifulSoup(html, "html.parser")
        files = parse_files(soup)

        print("발견한 첨부 파일 수: %d" % len(files))
        for i, item in enumerate(files, 1):
            print(
                "[%d] pathNum=%s fileUUID=%s filename=%r"
                % (i, item["pathNum"], item["fileUUID"], item["filename"])
            )
            saved = download_file(
                item["pathNum"], item["fileUUID"], item["filename"]
            )
            print("  -> 저장: %s" % saved)
    else:
        run()
