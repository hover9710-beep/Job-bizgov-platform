# -*- coding: utf-8 -*-
from __future__ import annotations
import re, time
from typing import Any, Dict, List
import requests
from bs4 import BeautifulSoup

BASE_URL   = "https://www.k-startup.go.kr"
LIST_URL   = f"{BASE_URL}/web/contents/bizpbanc-ongoing.do"
DETAIL_URL = f"{BASE_URL}/web/contents/bizpbanc-view.do"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)

def fetch_list_page(page: int = 1) -> List[Dict[str, Any]]:
    try:
        res = SESSION.get(LIST_URL, params={"menuNo": "300021", "pbancSttusCode": "PBST001", "page": page}, timeout=15)
        res.raise_for_status()
    except Exception as e:
        print(f"[WARN] K-Startup 목록 실패 page={page}: {e}")
        return []
    soup = BeautifulSoup(res.text, "html.parser")
    items = []
    for li in soup.select("#bizPbancList ul li"):
        title_tag = li.select_one("p.tit")
        title = title_tag.get_text(strip=True) if title_tag else ""
        if not title or title.upper() in ("MENU", "NONE"):
            continue
        a_tag = li.select_one("a[href]")
        if not a_tag:
            continue
        m = re.search(r"go_view\((\d+)\)", a_tag.get("href", ""))
        if not m:
            continue
        pbanc_sn = m.group(1)
        all_text = li.get_text(" ", strip=True)
        date_matches = re.findall(r'(\d{4})[.\-](\d{2})[.\-](\d{2})', all_text)
        dates = [f"{m[0]}-{m[1]}-{m[2]}" for m in date_matches]
        receipt_start = dates[0] if len(dates) >= 1 else ""
        receipt_end = dates[-1] if len(dates) >= 2 else ""
        org_tag = li.select_one(".organ, .agency, .org")
        org = org_tag.get_text(strip=True) if org_tag else "창업진흥원"
        items.append({
            "pbancSn": pbanc_sn,
            "title": title,
            "org": org,
            "deadline": receipt_end,
            "url": f"{DETAIL_URL}?pbancSn={pbanc_sn}",
            "source": "kstartup",
            "receipt_start": receipt_start,
            "receipt_end": receipt_end,
            "biz_start": "", "biz_end": "",
            "description": "", "attachments": [],
        })
    return items

def fetch_detail(pbanc_sn: str) -> Dict[str, Any]:
    try:
        res = SESSION.get(DETAIL_URL, params={"pbancSn": pbanc_sn}, timeout=15)
        res.raise_for_status()
    except Exception as e:
        print(f"[WARN] K-Startup 상세 실패 {pbanc_sn}: {e}")
        return {}
    soup = BeautifulSoup(res.text, "html.parser")
    result: Dict[str, Any] = {}
    attachments = []
    for a in soup.select("a[href*='download'], a[onclick*='download']"):
        name = a.get_text(strip=True)
        href = a.get("href") or ""
        if name:
            attachments.append({"name": name, "url": href if href.startswith("http") else BASE_URL + href})
    result["attachments"] = attachments
    return result

def fetch_all(max_pages: int = 30) -> List[Dict[str, Any]]:
    all_items: List[Dict[str, Any]] = []
    seen: set = set()
    for page in range(1, max_pages + 1):
        page_items = fetch_list_page(page)
        print(f"[K-Startup] page={page} items={len(page_items)}")
        if not page_items:
            break
        new = 0
        for item in page_items:
            if item["pbancSn"] not in seen:
                seen.add(item["pbancSn"])
                all_items.append(item)
                new += 1
        if new == 0:
            break
        time.sleep(0.5)
    print(f"[K-Startup] 총 {len(all_items)}건")
    return all_items

def run() -> List[Dict[str, Any]]:
    items = fetch_all()
    for item in items:
        time.sleep(0.3)
        detail = fetch_detail(item["pbancSn"])
        for k in ("receipt_start","receipt_end","biz_start","biz_end","description","attachments"):
            if detail.get(k):
                item[k] = detail[k]
    return items

if __name__ == "__main__":
    sample = fetch_list_page(1)
    for s in sample[:3]:
        print(s)
