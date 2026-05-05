# -*- coding: utf-8 -*-
"""한국수산회 K-Seafood Trade (biz.k-seafoodtrade.kr) 모집공고 목록 → biz_projects 저장.

- 메서드: GET, 한 페이지 20건
- 페이지네이션: ?biz_data=<Base64(startPage=N&...)>||  (N = 0,20,40,...)
- 카테고리: 전체만 수집 (part_idx 없이)
- AT 사업(수행기관=한국농수산식품유통공사)은 백로그 024 AT 커넥터와 중복 → skip
- dedup: 상세 URL의 biz_data Base64에서 idx 추출 → in-memory 키
- 상세 요청 없음 (목록만)
"""
from __future__ import annotations

import base64
import os
import re
import sqlite3
import time
from urllib.parse import urljoin

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

BASE = "https://biz.k-seafoodtrade.kr"
LIST_URL = f"{BASE}/apply/export_list.php"
DETAIL_BASE = f"{BASE}/apply/export_view.php"
PAGE_SIZE = 20
MAX_PAGES = 30  # 현재 표시 10페이지 + 안전 마진. 0건 응답 시 자동 종료.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": LIST_URL,
}

# AT 커넥터(백로그 024)와 중복되는 수행기관 — skip.
AT_ORG_TOKEN = "한국농수산식품유통공사"

DB_PATH = os.path.join(_ROOT, "db", "biz.db")
DEBUG_DIR = os.path.join(_ROOT, "data", "kseafood", "debug")

_SESSION = requests.Session()
_SESSION.headers.update(HEADERS)
_SESSION.verify = False

_PERIOD_RE = re.compile(r"(\d{4}-\d{2}-\d{2})[^~\-–∼]*[~\-–∼][^\d]*(\d{4}-\d{2}-\d{2})")
_BIZDATA_RE = re.compile(r"biz_data=([^|&]+)")
_IDX_RE = re.compile(r"(?:^|&)idx=(\d+)")


def _debug_save(name: str, html: str) -> None:
    os.makedirs(DEBUG_DIR, exist_ok=True)
    with open(os.path.join(DEBUG_DIR, name), "w", encoding="utf-8") as f:
        f.write(html)


def _map_status(raw: str) -> str:
    """모집중→접수중, 모집종료/마감→마감 (AT 커넥터와 표기 통일)."""
    s = raw.strip()
    if "모집중" in s or "접수중" in s:
        return "접수중"
    if "마감" in s or "종료" in s:
        return "마감"
    return ""


def _extract_idx(href: str) -> str | None:
    """상세 href의 biz_data Base64를 디코딩해서 idx 추출."""
    if not href:
        return None
    m = _BIZDATA_RE.search(href)
    if not m:
        return None
    try:
        decoded = base64.b64decode(m.group(1)).decode("utf-8", errors="replace")
    except Exception:
        return None
    im = _IDX_RE.search(decoded)
    return im.group(1) if im else None


def _make_page_biz_data(start_page: int) -> str:
    """페이지네이션 biz_data 생성 (사이트가 보낸 형식과 동일)."""
    qs = (
        f"startPage={start_page}&listNo=&table=&search_item_chk="
        "&search_mem_item=&search_biz_item=&search_order="
        "&search_day=&search_day_str=&pg="
    )
    return base64.b64encode(qs.encode("utf-8")).decode("ascii") + "||"


def parse_list_page(html: str, page_no: int) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        _debug_save(f"list_no_table_page_{page_no}.html", html)
        return []

    out: list[dict] = []
    tbody = table.find("tbody") or table
    for tr in tbody.find_all("tr", recursive=False):
        tds = tr.find_all("td")
        if len(tds) < 4:
            continue

        raw_status = tds[0].get_text(" ", strip=True)
        title_td = tds[1]
        title = title_td.get_text(" ", strip=True)
        if not title:
            continue

        period_text = tds[2].get_text(" ", strip=True)
        organization = tds[3].get_text(" ", strip=True)

        # AT 사업 skip — 백로그 024와 중복 방지
        if AT_ORG_TOKEN in organization:
            continue

        link = title_td.find("a")
        href = (link.get("href") if link else "") or ""
        idx = _extract_idx(href)
        if not idx:
            # 링크 없거나 파싱 실패 → 추적 불가, 스킵
            continue

        full_url = urljoin(LIST_URL, href)

        pm = _PERIOD_RE.search(period_text)
        start_date, end_date = (pm.group(1), pm.group(2)) if pm else ("", "")
        status = _map_status(raw_status)

        out.append({
            "title": title,
            "organization": organization,
            "source": "kseafood",
            "region": "전국",
            "url": full_url,
            "start_date": start_date,
            "end_date": end_date,
            "status": status,
            "summary": "",
            "period_text": period_text,
            "ministry": "해양수산부",
            "executing_agency": organization,
            "raw_status": raw_status,
            "receipt_start": start_date,
            "receipt_end": end_date,
            "site": "kseafood",
            # 내부 dedup 용 (DB 컬럼 없으면 자동 제외됨)
            "kseafood_idx": idx,
        })

    if not out:
        _debug_save(f"list_parse_empty_page_{page_no}.html", html)
    return out


def fetch_list_page(page_no: int) -> str:
    """page_no는 1부터. startPage = (page_no-1) * PAGE_SIZE."""
    if page_no == 1:
        params = None
    else:
        params = {"biz_data": _make_page_biz_data((page_no - 1) * PAGE_SIZE)}
    res = _SESSION.get(LIST_URL, params=params, timeout=20)
    res.raise_for_status()
    res.encoding = res.apparent_encoding or "utf-8"
    return res.text


def collect_all_pages() -> tuple[list[dict], dict]:
    """수집 + 통계 반환. 통계: skipped_at, status_counts, org_counts."""
    by_idx: dict[str, dict] = {}
    skipped_at_total = 0
    status_counts: dict[str, int] = {}
    org_counts: dict[str, int] = {}

    for page_no in range(1, MAX_PAGES + 1):
        try:
            html = fetch_list_page(page_no)
        except requests.RequestException as e:
            print(f"[KSEAFOOD] 목록 HTTP 실패 page={page_no}: {e}")
            resp = getattr(e, "response", None)
            body = (resp.text if resp is not None else "") or ""
            if body:
                _debug_save(f"list_http_error_page_{page_no}.html", body)
            raise

        # AT skip 카운트는 raw 파싱 단계로 다시 한 번 측정 (parse_list_page는 이미 skip한 결과)
        soup = BeautifulSoup(html, "html.parser")
        tbody = soup.find("table").find("tbody") if soup.find("table") else None
        raw_rows = tbody.find_all("tr", recursive=False) if tbody else []
        page_skipped_at = sum(
            1 for tr in raw_rows
            if len(tr.find_all("td")) >= 4
            and AT_ORG_TOKEN in tr.find_all("td")[3].get_text(" ", strip=True)
        )
        skipped_at_total += page_skipped_at

        items = parse_list_page(html, page_no)
        if not items and not raw_rows:
            print(f"[KSEAFOOD] page {page_no}: tbody 비어있음 → 종료")
            break

        new_count = 0
        for it in items:
            key = it["kseafood_idx"]
            if key in by_idx:
                continue
            by_idx[key] = it
            new_count += 1
            status_counts[it["status"] or "(빈값)"] = status_counts.get(it["status"] or "(빈값)", 0) + 1
            org_counts[it["organization"]] = org_counts.get(it["organization"], 0) + 1

        print(
            f"[KSEAFOOD] page {page_no:2d}: 수집 {len(items):2d}건 "
            f"(신규 {new_count:2d}, AT-skip {page_skipped_at:2d}) / 누적 {len(by_idx)}건"
        )

        if new_count == 0 and len(raw_rows) > 0:
            print(f"[KSEAFOOD] 신규 없음 → 종료")
            break

        if page_no < MAX_PAGES:
            time.sleep(0.5)

    stats = {
        "skipped_at_total": skipped_at_total,
        "status_counts": status_counts,
        "org_counts": org_counts,
    }
    return list(by_idx.values()), stats


def save_to_db(results: list[dict]) -> int:
    """INSERT OR IGNORE — url UNIQUE 가정. 존재하는 컬럼만 INSERT. 신규 건수 반환."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    existing = {str(r[1]) for r in cur.execute("PRAGMA table_info(biz_projects)").fetchall()}

    want = [
        "title", "organization", "source", "region", "url",
        "start_date", "end_date", "status", "summary", "period_text",
        "ministry", "executing_agency", "raw_status",
        "receipt_start", "receipt_end", "site",
    ]
    cols = [c for c in want if c in existing]
    if not cols:
        conn.close()
        raise RuntimeError("biz_projects에 INSERT 가능한 컬럼이 없습니다.")

    placeholders = ", ".join(["?"] * len(cols))
    col_sql = ", ".join(cols)
    sql = f"INSERT OR IGNORE INTO biz_projects ({col_sql}) VALUES ({placeholders})"

    inserted = 0
    for r in results:
        cur.execute(sql, tuple(r.get(c, "") for c in cols))
        inserted += cur.rowcount

    conn.commit()
    conn.close()
    print(
        f"[KSEAFOOD] DB 저장: 시도 {len(results)}건, 신규 {inserted}건 "
        f"(중복 {len(results) - inserted}건)"
    )
    return inserted


def run() -> None:
    results, stats = collect_all_pages()
    print()
    print("=" * 60)
    print(f"[KSEAFOOD] 수집 완료: {len(results)}건 (AT-skip 합계 {stats['skipped_at_total']}건)")
    print(f"[KSEAFOOD] 상태별: {stats['status_counts']}")
    print(f"[KSEAFOOD] 수행기관 분포 (상위 10):")
    top_orgs = sorted(stats["org_counts"].items(), key=lambda x: -x[1])[:10]
    for org, n in top_orgs:
        print(f"    {n:3d} | {org}")
    print("=" * 60)
    save_to_db(results)
    print(f"[KSEAFOOD] 완료.")


if __name__ == "__main__":
    run()
