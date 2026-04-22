# -*- coding: utf-8 -*-
from __future__ import annotations
import json, re, sys, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
import requests
from bs4 import BeautifulSoup

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from pipeline.bizinfo_dates import parse_date_range

BASE_URL   = "https://www.k-startup.go.kr"
LIST_URL   = f"{BASE_URL}/web/contents/bizpbanc-ongoing.do"
DETAIL_URL = f"{BASE_URL}/web/contents/bizpbanc-view.do"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)

OUT_DIR  = _ROOT / "data" / "kstartup"
OUT_PATH = OUT_DIR / "kstartup_all.json"

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
        receipt_start, receipt_end = parse_date_range(dates)
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
            "period_text": all_text,
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

def _normalize_for_pipeline(item: Dict[str, Any]) -> Dict[str, Any]:
    """파이프라인(merge_jb → update_db)이 기대하는 표준 필드로 변환."""
    collected_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "title": item.get("title", ""),
        "organization": item.get("org", "") or "창업진흥원",
        "ministry": "중소벤처기업부",
        "executing_agency": item.get("org", "") or "창업진흥원",
        "source": "kstartup",
        "site": "k-startup",
        "start_date": item.get("receipt_start", ""),
        "end_date": item.get("receipt_end", ""),
        "status": "진행",
        "url": item.get("url", ""),
        "description": item.get("description", ""),
        "attachments": item.get("attachments", []),
        "pbancSn": item.get("pbancSn", ""),
        "period_text": item.get("period_text", ""),
        "collected_at": collected_at,
    }


def save_json(items: List[Dict[str, Any]], out_path: Path = OUT_PATH) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    normalized = [_normalize_for_pipeline(it) for it in items]
    out_path.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[K-Startup] saved: {out_path} ({len(normalized)}건)", flush=True)
    return out_path


def run(with_detail: bool = False) -> List[Dict[str, Any]]:
    """목록 전체 수집 → JSON 저장. with_detail=True 면 상세(attachments)까지 수집."""
    items = fetch_all()
    if with_detail:
        for item in items:
            time.sleep(0.3)
            detail = fetch_detail(item["pbancSn"])
            for k in ("receipt_start", "receipt_end", "biz_start", "biz_end",
                      "description", "attachments"):
                if detail.get(k):
                    item[k] = detail[k]
    save_json(items)
    return items


if __name__ == "__main__":
    # 파이프라인 진입점: 전체 수집 후 kstartup_all.json 저장
    run(with_detail=False)
