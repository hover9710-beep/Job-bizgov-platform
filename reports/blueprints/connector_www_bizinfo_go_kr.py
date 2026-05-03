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
# 목록은 pageNo 단독이 아니라 cpage 로 페이지 전환 (pageNo=1 고정)
LIST_PAGE_ROWS = 15
_DETAIL_ID_RE = re.compile(r"[?&](?:seq|id|no|nttId|pblancId)=([^&#]+)", re.I)
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


def _list_cell_date(txt: str) -> str:
    """목록 행에서 날짜 셀만 골라낸다 (마지막 열은 조회수 등 숫자일 수 있음)."""
    t = (txt or "").strip()
    if not t:
        return ""
    if re.match(r"^\d{4}-\d{1,2}-\d{1,2}$", t):
        return t
    if re.match(r"^\d{4}[./]\d{1,2}[./]\d{1,2}$", t):
        return t
    return ""


def _pick_list_date_from_row(cols: list) -> str:
    """여러 td 중 YYYY-MM-DD 형태(또는 유사)인 셀을 우선."""
    for td in cols:
        raw = td.get_text(" ", strip=True)
        if _list_cell_date(raw):
            return raw
    # 구버전 레이아웃: 마지막-1 등
    if len(cols) >= 2:
        for idx in (len(cols) - 2, len(cols) - 1):
            if 0 <= idx < len(cols):
                raw = cols[idx].get_text(" ", strip=True)
                if _list_cell_date(raw):
                    return raw
    return cols[-1].get_text(strip=True) if cols else ""


def parse_bizinfo_list_html(html: str) -> list[dict]:
    """목록 HTML에서 공고 행 추출. 상세 URL의 pblancId·seq 등을 식별자로 사용."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict] = []
    for row in soup.select("table tbody tr"):
        cols = row.find_all("td")
        if len(cols) < 2:
            continue
        a = row.find("a", href=True)
        if not a:
            continue
        href = a.get("href", "")
        seq_m = _DETAIL_ID_RE.search(href)
        org = ""
        if len(cols) >= 3:
            candidates = [cols[1], cols[2]] if len(cols) > 2 else [cols[1]]
            for c in candidates:
                txt = c.get_text(strip=True)
                if txt and txt != a.get_text(strip=True):
                    org = txt
                    break
        out.append(
            {
                "seq": seq_m.group(1).strip() if seq_m else "",
                "title": a.get_text(strip=True),
                "organization": org,
                "date": _pick_list_date_from_row(cols),
            }
        )
    return out


def fetch_list(session, page=1):
    """page 인자는 목록 페이지 인덱스(cpage). pageNo=1·rows 고정과 함께 전달."""
    params = {"pageNo": 1, "rows": LIST_PAGE_ROWS, "cpage": int(page)}
    r = session.get(LIST_API, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return parse_bizinfo_list_html(r.text)


def _extract_period_status_from_detail_table(soup):
    """상세 페이지 테이블에서 접수기간·상태 추출."""
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
            for k in ("접수기간", "신청기간", "공고기간", "모집기간", "사업기간", "모집기간")
        ):
            period = val or period
        if any(
            k in label
            for k in ("공고상태", "진행상태", "접수상태")
        ) or label.strip() in ("상태",):
            status = val or status
    return period, status


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
    organization = ""
    for th in soup.select("th"):
        label = th.get_text(" ", strip=True)
        if "주관기관" not in label and "수행기관" not in label and "담당기관" not in label and "기관명" not in label:
            continue
        td = th.find_next("td")
        if td:
            organization = td.get_text(" ", strip=True)
            if organization:
                break
    if not organization:
        m = re.search(r"(?:주관기관|수행기관|담당기관|기관명)\s*[:：]\s*([^\n\r<]+)", r.text)
        if m:
            organization = m.group(1).strip()
    period_td, status_td = _extract_period_status_from_detail_table(soup)
    uuid_pat = re.compile(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
        r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    )
    uuids = list(dict.fromkeys(uuid_pat.findall(r.text)))
    return {
        "seq": seq,
        "title": title,
        "body": body,
        "organization": organization,
        "period": period_td,
        "status": status_td,
        "url": url,
        "uuid_list": uuids,
    }


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
