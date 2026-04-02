# connector_www_bizinfo_go_kr.py  -  자동 생성된 BizGovPlanner 커넥터
# 사이트:   https://www.bizinfo.go.kr
# 신뢰도:   70%
# 첨부전략: UNKNOWN
# 생성도구: auto_connector_v2.py

from __future__ import annotations
import json, logging, re
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

log = logging.getLogger("www_bizinfo_go_kr")

BASE_DIR       = Path(__file__).parent
DATA_DIR       = BASE_DIR / "data" / "www_bizinfo_go_kr"
JSON_DIR       = DATA_DIR / "json"
FILES_DIR      = DATA_DIR / "files"

BASE_URL       = "https://www.bizinfo.go.kr"
LIST_API       = "https://www.bizinfo.go.kr/sii/siia/selectSIIA200View.do"
DETAIL_PATTERN = "https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?hashCode=&rowsSel=&rows=15&cpage=&cat=&schPblancDiv=&schJrsdCodeTy=&schWntyAt=&schAreaDetailCodes=&schEndAt=N&orderGb=&sort=&preKeywords=&condition=&condition1=&keyword=&pblancId={seq}"
ATTACH_URL     = ""
TIMEOUT        = 15

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
}


def build_session(verify=True):
    s = requests.Session()
    s.headers.update(HEADERS)
    s.verify = verify
    return s


def fetch_list(session, page=1):
    params = {"pageNo": page}
    r = session.get(LIST_API, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    rows = soup.select("table tbody tr")
    out  = []
    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 2:
            continue
        a = row.find("a", href=True)
        if not a:
            continue
        href  = a.get("href", "")
        seq_m = re.search(r"[?&](?:seq|id|no|nttId)=(\w+)", href)
        out.append({
            "seq":   seq_m.group(1) if seq_m else "",
            "title": a.get_text(strip=True),
            "date":  cols[-1].get_text(strip=True) if cols else "",
        })
    return out


def fetch_detail(session, seq):
    url  = DETAIL_PATTERN.replace("{seq}", str(seq))
    r    = session.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    title = ""
    for sel in ["h3.view-title","h4.subject",".board-view-title","td.title"]:
        t = soup.select_one(sel)
        if t:
            title = t.get_text(strip=True)
            break
    body = ""
    for sel in [".board-view-content",".view-content","#content","td.content"]:
        t = soup.select_one(sel)
        if t:
            body = t.get_text("\n", strip=True)
            break
    uuid_pat = re.compile(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
        r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    )
    uuids = list(dict.fromkeys(uuid_pat.findall(r.text)))
    return {"seq": seq, "title": title, "body": body, "url": url, "uuid_list": uuids}


def download_attach(session, identifier, save_dir=FILES_DIR):
    # TODO: UNKNOWN 전략에 맞게 구현 필요
    log.warning("download_attach: 수동 구현 필요")
    return None


def run_pipeline(max_pages=3, verify=True):
    JSON_DIR.mkdir(parents=True, exist_ok=True)
    session    = build_session(verify=verify)
    all_items  = []
    for page in range(1, 1 + max_pages):
        log.info("목록 수집: page=%s", page)
        items = fetch_list(session, page=page)
        if not items:
            break
        all_items.extend(items)
    log.info("총 %d건 수집", len(all_items))
    for item in all_items:
        seq = item.get("seq")
        if not seq:
            continue
        detail = fetch_detail(session, seq)
        item.update(detail)
        for uuid in detail.get("uuid_list", []):
            download_attach(session, uuid)
    out = JSON_DIR / "www_bizinfo_go_kr_all.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(all_items, f, ensure_ascii=False, indent=2)
    log.info("저장: %s", out)


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    verify = "--no-verify" not in sys.argv
    run_pipeline(verify=verify)
