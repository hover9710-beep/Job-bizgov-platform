# -*- coding: utf-8 -*-
"""전북테크노파크(jbtp.or.kr) 공고 목록 수집 → biz_projects 저장.

표준 4단계 분리 (docs/architecture/connector_standardization.md):
  1) fetch    : page_no → HTML
  2) parse    : HTML → list[RawRow]   (site-specific 원시 필드)
  3) normalize: RawRow → CanonicalRecord (biz_projects 표준 키)
  4) save     : _common.save_to_db 위임 (URL UNIQUE, PRAGMA 컬럼 검사)

백로그 029 통째 sync (v2→v1, 2026-05-12 밤):
  - notice_chk / notice_order / start_date 추출이 connector 내장 → backfill 의존 제거
  - url 정규화 (_normalize_detail_url) 통합 — 사이트 a[href] 파라미터 순서 변경 대응
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from connectors._common import (  # noqa: E402
    debug_save,
    make_session,
    paginate,
    save_to_db,
)

# ===== 사이트 설정 =====
SOURCE_NAME = "jbtp"
ORG_NAME = "전북테크노파크"
REGION = "전북"
BASE = "https://www.jbtp.or.kr"
BASE_LIST = (
    f"{BASE}/board/list.jbtp?"
    "boardId=BBS_0000006&menuCd=DOM_000000102001000000&paging=ok&pageNo={page}"
)
MAX_PAGES = 9

COLS = [
    "title",
    "organization",
    "source",
    "region",
    "url",
    "start_date",
    "end_date",
    "status",
    "summary",
    "period_text",
    "notice_chk",
    "notice_order",
]

_SESSION = make_session()
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_DATASID_RE = re.compile(r"dataSid=(\d+)")


def _normalize_detail_url(href: str) -> str:
    # 사이트가 2026-05 a[href] 파라미터 순서를 menuCd&boardId&dataSid 로 변경.
    # 옛 row(boardId&dataSid&menuCd) 와 url string 매칭 위해 옛 형식으로 통일 (idx_url UNIQUE 호환).
    m = _DATASID_RE.search(href or "")
    if not m:
        return urljoin(BASE, href)
    return (
        f"{BASE}/board/view.jbtp?"
        f"boardId=BBS_0000006&dataSid={m.group(1)}&menuCd=DOM_000000102001000000"
    )


# ===== 1) fetch =====
def fetch(page_no: int) -> str:
    url = BASE_LIST.format(page=page_no)
    res = _SESSION.get(url, timeout=15)
    res.raise_for_status()
    return res.text


# ===== 2) parse — HTML → list[RawRow] =====
def parse(html: str, page_no: int) -> list[dict]:
    """RawRow 키:
      data_sid       : 상세 URL ID (dedup key + notice_order 정렬 키)
      href           : 상세 URL 경로 (상대)
      title          : 원시 제목
      raw_dday_text  : td.t_dday 텍스트 (status 결정용)
      raw_date_text  : td.t_date 텍스트 (end_date 결정용)
      row_text       : 행 전체 텍스트 (date fallback)
      is_notice      : td[0].class에 'notice' 포함 여부
      reg_date_text  : td[6] 등록일 원시 텍스트 (start_date 추출)
      seq_text       : td[0] 텍스트 — 일반글의 사이트 표시 seq (예: '2198')
    """
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict] = []
    for row in soup.select("table tbody tr"):
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
        tds = row.select("td")
        td0_cls = tds[0].get("class") if tds else None
        is_notice = bool(td0_cls and "notice" in td0_cls)
        reg_date_text = tds[6].get_text(" ", strip=True) if len(tds) >= 7 else ""
        seq_text = tds[0].get_text(strip=True) if tds else ""
        dday_td = row.select_one("td.t_dday")
        date_td = row.select_one("td.t_date")
        out.append(
            {
                "data_sid": m.group(1),
                "href": href,
                "title": title,
                "raw_dday_text": dday_td.get_text(" ", strip=True) if dday_td else "",
                "raw_date_text": date_td.get_text(" ", strip=True) if date_td else "",
                "row_text": row.get_text(" ", strip=True),
                "is_notice": is_notice,
                "reg_date_text": reg_date_text,
                "seq_text": seq_text,
            }
        )
    if not out:
        debug_save(SOURCE_NAME, f"list_parse_fail_page_{page_no}.html", html)
    return out


# ===== 3) normalize — RawRow → CanonicalRecord =====
def normalize(raw: dict) -> dict:
    end_date = _extract_end_date(raw["raw_date_text"], raw["row_text"])
    status = _map_status(raw["raw_dday_text"])
    start_date = _extract_start_date(raw.get("reg_date_text", ""))
    notice_chk = 1 if raw.get("is_notice") else 0
    if notice_chk:
        try:
            notice_order = int(raw["data_sid"])
        except (TypeError, ValueError):
            notice_order = 0
    else:
        seq = (raw.get("seq_text") or "").strip()
        try:
            notice_order = int(seq)
        except (TypeError, ValueError):
            try:
                notice_order = int(raw["data_sid"])
            except (TypeError, ValueError):
                notice_order = 0
    return {
        "title": raw["title"],
        "organization": ORG_NAME,
        "source": SOURCE_NAME,
        "region": REGION,
        "url": _normalize_detail_url(raw["href"]),
        "start_date": start_date,
        "end_date": end_date,
        "status": status,
        "summary": "",
        "period_text": end_date,
        "notice_chk": notice_chk,
        "notice_order": notice_order,
    }


def _extract_end_date(date_cell_text: str, row_text: str) -> str:
    m = _DATE_RE.search(date_cell_text or "")
    if m:
        return m.group(1)
    dates = _DATE_RE.findall(row_text or "")
    return dates[0] if dates else ""


def _extract_start_date(reg_text: str) -> str:
    m = _DATE_RE.search(reg_text or "")
    return m.group(1) if m else ""


def _map_status(dday_text: str) -> str:
    if "접수중" in dday_text:
        return "접수중"
    if "마감" in dday_text:
        return "마감"
    return ""


# ===== 4) save (위임) =====
def save(records: list[dict]) -> None:
    filtered = [{k: r.get(k, "") for k in COLS} for r in records]
    save_to_db(filtered, SOURCE_NAME)


def run() -> None:
    raw_rows = paginate(
        fetch_fn=fetch,
        parse_fn=parse,
        source_name=SOURCE_NAME,
        max_pages=MAX_PAGES,
        sleep=0.5,
        key="data_sid",
    )
    records = [normalize(r) for r in raw_rows]
    save(records)
    print(f"[{SOURCE_NAME}] 완료: {len(records)}건")


if __name__ == "__main__":
    run()
