# -*- coding: utf-8 -*-
"""
기업마당(bizinfo.go.kr) 전체 목록 수집 — 키워드 필터 없이 페이지 순회.

실행(프로젝트 루트):
  py connectors/connector_bizinfo.py
      → 기본: 전체 목록만 수집(상세 생략, 수 분 내 완료). 전체수집→서버필터 전략에 맞춤.
  py connectors/connector_bizinfo.py --with-detail
      → 공고별 상세까지 수집(기간·본문 보강, 시간 매우 김).
  py connectors/connector_bizinfo.py --max-pages 5

저장: data/bizinfo/json/bizinfo_all.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reports.blueprints.connector_www_bizinfo_go_kr import (
    BASE_URL,
    DETAIL_PATTERN,
    HEADERS,
    LIST_API,
    LIST_PAGE_ROWS,
    TIMEOUT,
    build_session,
    parse_bizinfo_list_html,
)

_PIPELINE = ROOT / "pipeline"
if str(_PIPELINE) not in sys.path:
    sys.path.insert(0, str(_PIPELINE))
from project_quality import normalize_status, parse_period_from_item

OUT_JSON = ROOT / "data" / "bizinfo" / "json" / "bizinfo_all.json"

def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def fetch_total_count(
    session: requests.Session,
) -> Tuple[Optional[int], int]:
    """
    사이트에 표시된 전체 공고 수(가능하면)와 페이지당 행 수.
    총건 파싱 실패 시 (None, LIST_PAGE_ROWS).
    """
    try:
        r = session.get(
            LIST_API,
            params={"pageNo": 1, "rows": LIST_PAGE_ROWS, "cpage": 1},
            timeout=max(TIMEOUT, 25),
        )
        r.raise_for_status()
    except requests.RequestException:
        return None, LIST_PAGE_ROWS

    html = r.text
    for pat in (
        r"총\s*([\d,]+)\s*건",
        r"전체\s*([\d,]+)\s*건",
        r"total(?:Count|Records)?\s*[=:]\s*['\"]?(\d+)",
        r"건수\s*[:：]?\s*([\d,]+)",
    ):
        m = re.search(pat, html, re.I)
        if m:
            try:
                return int(m.group(1).replace(",", "")), LIST_PAGE_ROWS
            except (ValueError, IndexError):
                continue
    # 기업마당 목록: "전체(1229)" 형태가 span 안에 있음 (인코딩에 따라 글자 깨질 수 있음)
    if "hashAll" in html:
        i = html.find("hashAll")
        chunk = html[max(0, i - 400) : i + 400]
        m = re.search(r"\(([\d,]+)\)\s*</span>", chunk)
        if m:
            try:
                n = int(m.group(1).replace(",", ""))
                if n >= 50:
                    return n, LIST_PAGE_ROWS
            except ValueError:
                pass
    candidates: List[int] = []
    for m in re.finditer(r"\(([\d,]+)\)\s*</span>", html):
        try:
            n = int(m.group(1).replace(",", ""))
            if n >= 200:
                candidates.append(n)
        except ValueError:
            continue
    if candidates:
        return max(candidates), LIST_PAGE_ROWS
    return None, LIST_PAGE_ROWS


def fetch_list_page(session: requests.Session, page: int) -> str:
    """cpage=page 목록 HTML."""
    r = session.get(
        LIST_API,
        params={"pageNo": 1, "rows": LIST_PAGE_ROWS, "cpage": int(page)},
        timeout=max(TIMEOUT, 25),
    )
    r.raise_for_status()
    return r.text


def parse_list_items(html: str) -> List[Dict[str, Any]]:
    """목록 HTML → 행 dict (seq, title, organization, date, href). 필터 없음."""
    return parse_bizinfo_list_html(html)


def _detail_url_from_seq(seq: str) -> str:
    if not seq:
        return ""
    return DETAIL_PATTERN.replace("{seq}", str(seq))


def fetch_detail(url: str, session: requests.Session) -> Dict[str, Any]:
    """
    상세 페이지 요청·파싱. url이 비어 있으면 빈 dict.
    blueprint fetch_detail(seq)와 동일 정보 + url 키.
    """
    out: Dict[str, Any] = {}
    if not (url or "").strip():
        return out
    seq_m = re.search(r"pblancId=([^&]+)", url, re.I)
    seq = seq_m.group(1).strip() if seq_m else ""
    if not seq:
        try:
            r = session.get(url, timeout=max(TIMEOUT, 25))
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            return _parse_detail_soup(soup, url)
        except requests.RequestException:
            return out

    detail_url = _detail_url_from_seq(seq)
    try:
        r = session.get(detail_url, timeout=max(TIMEOUT, 25))
        r.raise_for_status()
    except requests.RequestException:
        return out
    soup = BeautifulSoup(r.text, "html.parser")
    return _parse_detail_soup(soup, detail_url)


def _extract_period_status_from_detail_table(soup: BeautifulSoup) -> Tuple[str, str]:
    period = ""
    status = ""
    for th in soup.select("th"):
        label = th.get_text(" ", strip=True)
        td = th.find_next("td")
        if not td:
            continue
        val = td.get_text(" ", strip=True)
        if any(
            k in label
            for k in ("접수기간", "신청기간", "공고기간", "모집기간", "사업기간")
        ):
            period = val or period
        if any(k in label for k in ("공고상태", "진행상태", "접수상태")) or label.strip() in (
            "상태",
        ):
            status = val or status
    return period, status


def _extract_labeled_th_td(soup: BeautifulSoup, labels: Tuple[str, ...]) -> str:
    for th in soup.select("th"):
        label = th.get_text(" ", strip=True)
        if not any(l in label for l in labels):
            continue
        td = th.find_next("td")
        if td:
            v = td.get_text(" ", strip=True)
            if v:
                return v
    return ""


def _extract_labeled_dl(soup: BeautifulSoup, labels: Tuple[str, ...]) -> str:
    for dt in soup.find_all("dt"):
        label = dt.get_text(" ", strip=True)
        if not any(l in label for l in labels):
            continue
        dd = dt.find_next_sibling("dd")
        if dd:
            v = dd.get_text(" ", strip=True)
            if v:
                return v
    return ""


def _extract_ministry(soup: BeautifulSoup, raw_text: str) -> str:
    for labels in (("소관부처", "소관부서"),):
        v = _extract_labeled_th_td(soup, labels) or _extract_labeled_dl(soup, labels)
        if v:
            return v
    for pat in (
        r"소관부(?:처|서)\s*[:：]\s*([^\n\r]+)",
        r"소관\s*[:：]\s*([^\n\r]+)",
    ):
        m = re.search(pat, raw_text)
        if m:
            return m.group(1).strip()
    return ""


def _extract_executing_agency(soup: BeautifulSoup, raw_text: str) -> str:
    for labels in (("사업수행기관",), ("수행기관",), ("지원기관",)):
        v = _extract_labeled_th_td(soup, labels) or _extract_labeled_dl(soup, labels)
        if v:
            return v
    for pat in (
        r"사업수행기관\s*[:：]\s*([^\n\r]+)",
        r"(?:수행기관|지원기관)\s*[:：]\s*([^\n\r]+)",
    ):
        m = re.search(pat, raw_text)
        if m:
            return m.group(1).strip()
    return ""


def _extract_organization_legacy(soup: BeautifulSoup, raw_text: str) -> str:
    for labels in (
        ("주관기관",),
        ("담당기관",),
        ("지원기관",),
        ("기관명",),
        ("수행기관",),
    ):
        v = _extract_labeled_th_td(soup, labels) or _extract_labeled_dl(soup, labels)
        if v:
            return v
    m = re.search(
        r"(?:주관기관|수행기관|담당기관|지원기관|기관명)\s*[:：]\s*([^\n\r]+)",
        raw_text,
    )
    if m:
        return m.group(1).strip()
    return ""


def _parse_detail_soup(soup: BeautifulSoup, page_url: str) -> Dict[str, Any]:
    title = ""
    for sel in ["h3.view-title", "h4.subject", ".board-view-title", "td.title"]:
        t = soup.select_one(sel)
        if t:
            title = t.get_text(strip=True)
            break
    body = ""
    for sel in [".board-view-content", ".view-content", "#content", "td.content"]:
        t = soup.select_one(sel)
        if t:
            body = t.get_text("\n", strip=True)
            break
    raw = soup.get_text("\n", strip=True)
    ministry = _extract_ministry(soup, raw)
    executing_agency = _extract_executing_agency(soup, raw)
    organization = _extract_organization_legacy(soup, raw)
    if not organization and executing_agency:
        organization = executing_agency
    period, status_td = _extract_period_status_from_detail_table(soup)
    return {
        "title": title,
        "body": body,
        "organization": organization,
        "ministry": ministry,
        "executing_agency": executing_agency,
        "period": period,
        "status": status_td,
        "url": page_url,
    }


def _row_to_standard(
    row: Dict[str, Any],
    *,
    collected_at: str,
    detail: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    seq = str(row.get("seq") or "").strip()
    href = ""
    soup_row = row.get("_href")
    if soup_row:
        href = str(soup_row)
    list_url = urljoin(BASE_URL + "/", href.lstrip("/")) if href else _detail_url_from_seq(seq)

    title = str(row.get("title") or "").strip()
    org = str(row.get("organization") or "").strip()
    ministry = ""
    executing_agency = ""
    desc = ""
    sd, ed = "", ""
    st = normalize_status(str(row.get("status") or ""))

    if detail:
        if detail.get("title"):
            title = str(detail["title"]).strip() or title
        if detail.get("organization"):
            org = str(detail["organization"]).strip() or org
        if detail.get("ministry"):
            ministry = str(detail["ministry"]).strip()
        if detail.get("executing_agency"):
            executing_agency = str(detail["executing_agency"]).strip()
        desc = str(detail.get("body") or "").strip()
        period = str(detail.get("period") or "").strip()
        if period:
            sd, ed = parse_period_from_item(
                {"period": period, "start_date": sd, "end_date": ed}
            )
        if detail.get("status"):
            st = normalize_status(str(detail["status"]))
        if detail.get("url"):
            list_url = str(detail["url"]).strip() or list_url

    if not desc and row.get("date"):
        desc = str(row.get("date") or "").strip()

    return {
        "source": "bizinfo",
        "site": "bizinfo",
        "title": title,
        "organization": org or "기업마당",
        "ministry": ministry,
        "executing_agency": executing_agency,
        "url": list_url,
        "description": desc,
        "start_date": sd,
        "end_date": ed,
        "status": st,
        "collected_at": collected_at,
    }


def _augment_rows_with_hrefs(html: str, raw_rows: List[Dict[str, Any]]) -> None:
    """parse_bizinfo_list_html 과 동일 순서로 tr을 골라 href 부착."""
    soup = BeautifulSoup(html, "html.parser")
    trs: List[Any] = []
    for tr in soup.select("table tbody tr"):
        cols = tr.find_all("td")
        if len(cols) < 2:
            continue
        a = tr.find("a", href=True)
        if not a:
            continue
        trs.append(tr)
    for i, row in enumerate(raw_rows):
        if i < len(trs):
            a = trs[i].find("a", href=True)
            if a:
                row["_href"] = a.get("href") or ""


def run(
    *,
    max_pages: Optional[int] = None,
    no_detail: bool = False,
    out_path: Optional[Path] = None,
    verify_ssl: bool = True,
    delay_sec: float = 0.12,
) -> Dict[str, Any]:
    """run()의 개선: href를 HTML에서 직접 매핑 (BeautifulSoup 한 번만)."""
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass

    out_path = out_path or OUT_JSON
    out_path.parent.mkdir(parents=True, exist_ok=True)

    session = build_session(verify=verify_ssl)
    session.headers.update(HEADERS)

    site_total, rows_per_page = fetch_total_count(session)

    all_items: List[Dict[str, Any]] = []
    success_pages = 0
    failed_pages = 0
    page = 1
    prev_key = ""
    collected_at = _today_str()

    total_pages_hint: Optional[int] = None
    if site_total and rows_per_page > 0:
        total_pages_hint = (site_total + rows_per_page - 1) // rows_per_page

    print("[bizinfo crawler]", flush=True)
    print(
        f"site total: {site_total if site_total is not None else 'UNKNOWN'}",
        flush=True,
    )
    if total_pages_hint:
        print(f"pages: {total_pages_hint}", flush=True)
    else:
        print("pages: (순회로 결정)", flush=True)

    while True:
        if max_pages is not None and page > max_pages:
            break
        try:
            html = fetch_list_page(session, page)
        except requests.RequestException as exc:
            print(f"[warning] page {page} 목록 요청 실패: {exc}", flush=True)
            failed_pages += 1
            page += 1
            continue

        raw_rows = parse_list_items(html)
        if not raw_rows:
            break

        key = str(raw_rows[0].get("title", "")) + "|" + str(raw_rows[0].get("seq", ""))
        if page > 1 and key and key == prev_key:
            print(f"[warning] page {page}: 중복 목록 감지 → 종료", flush=True)
            break
        prev_key = key

        _augment_rows_with_hrefs(html, raw_rows)

        page_n = 0
        for row in raw_rows:
            href = str(row.get("_href") or "").strip()
            detail_url = urljoin(BASE_URL + "/", href.lstrip("/")) if href else _detail_url_from_seq(
                str(row.get("seq") or "")
            )
            detail: Dict[str, Any] = {}
            if not no_detail and detail_url:
                try:
                    detail = fetch_detail(detail_url, session)
                except Exception as exc:
                    print(
                        f"[warning] 상세 예외 (목록 유지): {str(exc)[:120]}",
                        flush=True,
                    )
                time.sleep(delay_sec)

            item = _row_to_standard(row, collected_at=collected_at, detail=detail if detail else None)
            if not item.get("url"):
                item["url"] = detail_url
            all_items.append(item)
            page_n += 1

        print(f"page {page}: {page_n}건", flush=True)
        success_pages += 1
        page += 1
        time.sleep(delay_sec)

    print(
        f"success_pages: {success_pages}  failed_pages: {failed_pages}  total_items: {len(all_items)}",
        flush=True,
    )

    out_path.write_text(json.dumps(all_items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {out_path}", flush=True)
    print(f"collected total: {len(all_items)}", flush=True)

    n = len(all_items)
    if site_total and site_total > 0:
        rate = n / site_total
        ok = rate >= 0.95 and failed_pages == 0
        label = "FULL" if ok else "PARTIAL"
    else:
        label = "FULL" if failed_pages == 0 and n > 0 else "PARTIAL"
    print(f"result: {label}", flush=True)

    return {
        "site_total": site_total,
        "rows_per_page": rows_per_page,
        "total_pages": total_pages_hint,
        "success_pages": success_pages,
        "failed_pages": failed_pages,
        "total_items": n,
        "out_path": str(out_path),
        "result": label,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="기업마당 전체 목록 수집")
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="최대 목록 페이지 (미지정 시 끝까지)",
    )
    parser.add_argument(
        "--with-detail",
        action="store_true",
        help="공고별 상세 페이지까지 요청 (기간·본문 보강, 대량 HTTP·시간 소요)",
    )
    parser.add_argument(
        "--no-detail",
        action="store_true",
        help="목록만 수집 (--with-detail 보다 우선)",
    )
    parser.add_argument(
        "--no-verify-ssl",
        action="store_true",
        help="SSL 검증 끄기",
    )
    parser.add_argument("--out", type=Path, default=None, help="출력 JSON 경로")
    args = parser.parse_args()

    if args.no_detail:
        no_detail = True
    elif args.with_detail:
        no_detail = False
    else:
        # 무인자 기본: 전체 목록만(서버 필터링 단계로 넘기기 전 단계)
        no_detail = True

    stats = run(
        max_pages=args.max_pages,
        no_detail=no_detail,
        out_path=args.out,
        verify_ssl=not args.no_verify_ssl,
    )
    return 0 if stats.get("total_items", 0) >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
