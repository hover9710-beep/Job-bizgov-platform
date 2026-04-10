import json
import os
import re
import sys
import urllib.parse
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pipeline.today_yesterday import save_today_snapshot
from pipeline.fields_normalize import extract_period_line_from_text, parse_dates_from_item

# =========================================================
# 기본 설정
# =========================================================
PROXY_BASE = "http://127.0.0.1:5000"
LIST_ENDPOINT = f"{PROXY_BASE}/api/jbexport/list"

JBEXPORT_BASE = "https://www.jbexport.or.kr"
DETAIL_BASE = f"{JBEXPORT_BASE}/other/spWork/spWorkSupportBusiness/detail1.do"
MENU_UUID = "402880867c8174de017c819251e70009"

LIST_LENGTH = 10
# 목록 API: 첫 요청은 큰 length로 시도 후, 필요 시 start 증가하며 전부 수집
LIST_FIRST_LENGTH = 1000
LIST_PAGE_LENGTH = 100
MAX_LIST_BATCHES = 200
MAX_PAGES = 100
TIMEOUT = 30
OPEN_STATUSES = {"접수중", "공고중"}

# 목록 API에 기간이 비어 있을 때 상세 HTML에서 접수기간·상태 보강 (기본 ON)
# 끄려면: JBEXPORT_FETCH_DETAIL_META=0
FETCH_DETAIL_META = True
_FETCH_DETAIL_META = FETCH_DETAIL_META and os.getenv(
    "JBEXPORT_FETCH_DETAIL_META", "1"
).strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)

DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

# today.json / yesterday.json 은 프로젝트 루트 기준 data/ (cwd 무관)
_SNAPSHOT_DATA_DIR = _ROOT / "data"
_SNAPSHOT_DATA_DIR.mkdir(parents=True, exist_ok=True)

JBEXPORT_DIR = DATA_DIR / "jbexport"
JBEXPORT_DIR.mkdir(parents=True, exist_ok=True)

ATTACH_DIR = JBEXPORT_DIR / "files"
ATTACH_DIR.mkdir(parents=True, exist_ok=True)


# =========================================================
# 공통 로그
# =========================================================
def log(message: str) -> None:
    print(message, flush=True)


# =========================================================
# 경로 함수
# =========================================================
def today_json_path(target_date: date) -> Path:
    return JBEXPORT_DIR / f"{target_date.isoformat()}.json"


def new_json_path() -> Path:
    return DATA_DIR / "jbexport_new.json"


# =========================================================
# 목록 응답에서 rows 꺼내기
# =========================================================
def rows_from_json(payload: Any) -> List[Any]:
    """DataTables 응답: data / aaData / rows 등."""
    if not isinstance(payload, dict):
        return []
    for key in ("data", "aaData", "rows", "resultList"):
        data = payload.get(key)
        if isinstance(data, list):
            return data
    return []


def records_total_from_json(payload: Any) -> Optional[int]:
    if not isinstance(payload, dict):
        return None
    for k in ("recordsTotal", "recordsFiltered", "iTotalRecords", "total"):
        v = payload.get(k)
        if v is None:
            continue
        try:
            return int(v)
        except (TypeError, ValueError):
            continue
    return None


# =========================================================
# 상세 HTML: BeautifulSoup으로 상태·기간 (merge_jb / 메일 필터용)
# =========================================================
def _period_dates_from_string(val: str) -> Tuple[str, str]:
    """접수기간 한 덩어리 → (start_date, end_date) ISO."""
    s = re.sub(r"\s+", " ", str(val or "")).strip()
    if not s:
        return "", ""
    sd, ed, _ = parse_dates_from_item({"기간": s, "period": s}, body_fallback=s)
    return sd or "", ed or ""


def parse_jbexport_detail_html(html: str) -> Dict[str, str]:
    """
    detail1.do HTML에서 status, start_date, end_date 추출.
    반환 키: status(원문에 가깝게), start_date, end_date (YYYY-MM-DD)
    """
    out: Dict[str, str] = {"status": "", "start_date": "", "end_date": ""}
    if not html or not str(html).strip():
        return out

    soup = BeautifulSoup(html, "html.parser")
    full_text = soup.get_text("\n", strip=True)

    def absorb_period(val: str) -> None:
        sd, ed = _period_dates_from_string(val)
        if sd:
            out["start_date"] = sd
        if ed:
            out["end_date"] = ed

    # 1) table: th / td
    for th in soup.find_all("th"):
        label = th.get_text(" ", strip=True)
        td = th.find_next_sibling("td")
        if not td:
            continue
        val = td.get_text(" ", strip=True)
        if not val:
            continue
        if any(k in label for k in ("접수기간", "신청기간", "모집기간", "공고기간", "사업기간")):
            absorb_period(val)
        if any(
            k in label
            for k in ("진행상태", "접수상태", "공고상태", "상태", "진행 상태")
        ):
            if len(val) < 80 and not re.search(r"function\s*\(", val):
                out["status"] = val

    # 2) dl dt / dd
    for dt in soup.find_all("dt"):
        label = dt.get_text(" ", strip=True)
        dd = dt.find_next_sibling("dd")
        if not dd:
            continue
        val = dd.get_text(" ", strip=True)
        if not val:
            continue
        if any(k in label for k in ("접수기간", "신청기간", "모집기간", "공고기간")):
            absorb_period(val)
        if any(k in label for k in ("진행상태", "접수상태", "공고상태", "상태")):
            if len(val) < 80:
                out["status"] = val

    # 3) 정규식 (플레인 텍스트)
    if not out["status"]:
        m = re.search(
            r"(?:진행상태|공고상태|접수상태|상태)\s*[:：]?\s*([^\n\r<]+?)(?:\n|$)",
            full_text,
            re.IGNORECASE,
        )
        if m:
            cand = re.sub(r"\s+", " ", m.group(1)).strip()
            if cand and len(cand) < 80:
                out["status"] = cand

    if not (out["start_date"] and out["end_date"]):
        line = extract_period_line_from_text(full_text)
        if line:
            absorb_period(line)

    if not (out["start_date"] and out["end_date"]):
        period, _st = extract_period_status_from_jbexport_html(html)
        if period:
            absorb_period(period)

    # 목록 HTML 정규식(태그 포함)으로 상태 보강
    if not out["status"]:
        _p2, st2 = extract_period_status_from_jbexport_html(html)
        if st2:
            out["status"] = st2

    return out


_DETAIL_SESSION: Optional[requests.Session] = None


def _get_detail_session() -> requests.Session:
    global _DETAIL_SESSION
    if _DETAIL_SESSION is None:
        _DETAIL_SESSION = requests.Session()
        _DETAIL_SESSION.verify = False
    return _DETAIL_SESSION


def fetch_jbexport_detail_fields(detail_url: str) -> Dict[str, str]:
    """상세 URL GET 후 parse_jbexport_detail_html. 실패 시 {}."""
    sess = _get_detail_session()
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.jbexport.or.kr/index.do",
    }
    try:
        res = sess.get(
            detail_url,
            headers=headers,
            timeout=TIMEOUT,
            verify=False,
        )
        res.raise_for_status()
        return parse_jbexport_detail_html(res.text)
    except Exception as e:
        print(f"[JBEXPORT ERROR] {detail_url}")
        print(e)
        return {}


# =========================================================
# 상세 HTML에서 접수기간·상태 (목록에 없을 때)
# =========================================================
def extract_period_status_from_jbexport_html(html: str) -> Tuple[str, str]:
    period = ""
    status = ""
    m = re.search(
        r"(?:접수기간|신청기간|공고기간|모집기간)\s*[:：]?\s*([^<\n\r]+?)(?:<|$)",
        html,
        re.IGNORECASE,
    )
    if m:
        period = re.sub(r"\s+", " ", m.group(1)).strip()
    m2 = re.search(
        r"(?:진행상태|공고상태|접수상태|상태)\s*[:：]?\s*([^<\n\r]+?)(?:<|$)",
        html,
        re.IGNORECASE,
    )
    if m2:
        status = re.sub(r"\s+", " ", m2.group(1)).strip()
    # 라벨 매칭 실패 시 본문에 나오는 YYYY-MM-DD 두 개로 기간 추정
    if not period:
        dates = re.findall(r"\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2}", html)
        uniq: List[str] = []
        for d in dates:
            if d not in uniq:
                uniq.append(d)
            if len(uniq) >= 2:
                break
        if len(uniq) >= 2:
            period = f"{uniq[0]} ~ {uniq[1]}"
        elif len(uniq) == 1:
            period = uniq[0]
    return period, status


def enrich_detail_meta_from_url(detail_url: str) -> Tuple[str, str]:
    """(기간 문자열, 상태 원문). parse_jbexport_detail_html 기반."""
    fields = fetch_jbexport_detail_fields(detail_url)
    sd = str(fields.get("start_date") or "").strip()
    ed = str(fields.get("end_date") or "").strip()
    if sd and ed:
        period = f"{sd} ~ {ed}"
    elif sd:
        period = sd
    else:
        period = ""
    status = str(fields.get("status") or "").strip()
    return period, status


# =========================================================
# 공고 1건 정규화
# =========================================================
def extract_announcement(row: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(row, dict):
        return None

    sp_seq = str(
        row.get("spSeq")
        or row.get("SP_SEQ")
        or row.get("seq")
        or row.get("SEQ")
        or ""
    ).strip()

    if not sp_seq:
        return None

    title = str(
        row.get("title")
        or row.get("사업명")
        or row.get("sj")
        or row.get("subject")
        or ""
    ).strip()

    period = str(
        row.get("period")
        or row.get("접수기간")
        or row.get("rcptPd")
        or row.get("사업기간")
        or row.get("rcptPdTxt")
        or row.get("dateRange")
        or row.get("applyPeriod")
        or ""
    ).strip()

    status = str(
        row.get("status")
        or row.get("상태")
        or row.get("ingYnNm")
        or row.get("progressStatus")
        or row.get("prgrsStts")
        or ""
    ).strip()

    detail_url = f"{DETAIL_BASE}?menuUUID={MENU_UUID}&spSeq={sp_seq}"

    if _FETCH_DETAIL_META:
        p2, s2 = enrich_detail_meta_from_url(detail_url)
        if p2:
            period = p2
        if s2:
            status = s2

    sd, ed, _ = parse_dates_from_item(
        {"기간": period, "period": period},
        body_fallback=period,
    )

    out = {
        "spSeq": sp_seq,
        "공고제목": title or f"spSeq={sp_seq}",
        "기관": "전북수출통합지원시스템",
        "기간": period,
        "상태": status,
        "상세URL": detail_url,
        "files": [],
        "start_date": sd,
        "end_date": ed,
        "status": status,
    }
    print(f"[jbexport] {out['status']} {out['start_date']}~{out['end_date']}")
    if _FETCH_DETAIL_META:
        item = {**out, "title": out.get("공고제목", "")}
        print(f"[jbexport-detail] {item.get('title', '')[:30]}")
        print(
            f"  status={item.get('status')} {item.get('start_date')}~{item.get('end_date')}"
        )
    return out


# =========================================================
# 전체 공고 수집
# =========================================================
def fetch_all_announcements() -> Tuple[List[Dict[str, Any]], int]:
    log("[수집 시작] JBEXPORT 전체 공고 수집 (목록 페이지네이션)")

    all_items: List[Dict[str, Any]] = []
    seen_urls = set()

    start = 0
    draw = 1
    length = LIST_FIRST_LENGTH
    records_total: Optional[int] = None
    cumulative_row_count = 0
    batch_idx = 0

    while batch_idx < MAX_LIST_BATCHES:
        payload: Dict[str, Any] = {
            "start": start,
            "length": length,
            "draw": draw,
        }
        log(
            "[jbexport-list] POST payload to list API: "
            + json.dumps(payload, ensure_ascii=False)
        )

        try:
            res = requests.post(
                LIST_ENDPOINT,
                json=payload,
                timeout=TIMEOUT,
            )
            res.raise_for_status()
            data = res.json()
        except Exception as e:
            log(f"[오류] LIST 요청 실패: {e}")
            break

        rows = rows_from_json(data)
        rt_batch = records_total_from_json(data)
        if records_total is None and rt_batch is not None:
            records_total = rt_batch

        if not rows:
            break

        cumulative_row_count += len(rows)
        log(
            f"[jbexport-list] batch start={start} length={length} "
            f"rows_this_batch={len(rows)} "
            f"cumulative={cumulative_row_count} recordsTotal={records_total}"
        )

        for row in rows:
            item = extract_announcement(row)
            if not item:
                continue

            url = item["상세URL"]
            if url in seen_urls:
                continue

            seen_urls.add(url)
            all_items.append(item)

        batch_idx += 1

        if records_total is not None and cumulative_row_count >= records_total:
            break

        start += len(rows)
        draw += 1
        if length == LIST_FIRST_LENGTH:
            length = LIST_PAGE_LENGTH

    titles = [
        str(x.get("공고제목") or x.get("title") or "") for x in all_items
    ]
    if titles:
        log(f"[jbexport-list] first 5 titles: {titles[:5]}")
        log(f"[jbexport-list] last 5 titles: {titles[-5:]}")
        if len(titles) >= 10:
            n = len(titles)
            idxs = [round(i * (n - 1) / 9) for i in range(10)]
            log(
                "[jbexport-list] sample titles (10 across full set): "
                + str([titles[i] for i in idxs])
            )
    log(f"[jbexport-list] final collected: {len(all_items)}")
    log(f"[수집 완료] 전체 공고 {len(all_items)}건")
    _st_filled = sum(
        1 for x in all_items if str(x.get("status") or x.get("상태") or "").strip()
    )
    log(
        f"[jbexport-detail] 상세 메타 적용 건수={len(all_items)} (FETCH_DETAIL_META={_FETCH_DETAIL_META}), "
        f"상태 비어있지 않음={_st_filled}"
    )
    return all_items, cumulative_row_count


# =========================================================
# 진행중 공고만 필터
# =========================================================
def filter_open_announcements(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    filtered: List[Dict[str, Any]] = []

    for item in results:
        status = str(item.get("상태") or "").strip()
        if status in OPEN_STATUSES:
            filtered.append(item)

    log(f"[필터] 진행중 공고 {len(filtered)}건")
    return filtered


def log_filter_stage_diagnosis(
    list_api_raw_rows: int,
    all_items: List[Dict[str, Any]],
    open_items: List[Dict[str, Any]],
) -> None:
    """
    Diagnostic only: counts and sample drops. Does not change filtering behavior.
    Date rules match pipeline/make_mail.py (is_active / is_new / is_ending_soon).
    """
    from pipeline.make_mail import is_active, is_ending_soon, is_new

    log("[filter-diag] === filtering stage (diagnostic) ===")
    log(f"[filter-diag] 1) total collected rows (list API, raw): {list_api_raw_rows}")
    log(f"[filter-diag] 2) JBEXPORT rows (after extract + URL dedupe): {len(all_items)}")
    log(
        f"[filter-diag] 3) after OPEN_STATUSES filter {OPEN_STATUSES}: {len(open_items)}"
    )

    n_active = sum(1 for x in all_items if is_active(x))
    n_new = sum(1 for x in all_items if is_new(x))
    n_end = sum(1 for x in all_items if is_ending_soon(x))
    log(
        "[filter-diag] 4) date flags on ALL collected items (make_mail date rules): "
        f"is_active={n_active} is_new={n_new} is_ending_soon={n_end}"
    )

    not_in_open = [
        x for x in all_items if str(x.get("상태") or "").strip() not in OPEN_STATUSES
    ]
    open_not_active = [
        x
        for x in all_items
        if str(x.get("상태") or "").strip() in OPEN_STATUSES and not is_active(x)
    ]

    sample: List[Tuple[Dict[str, Any], str]] = []
    for item in not_in_open:
        st = str(item.get("상태") or "").strip()
        sample.append(
            (
                item,
                f"excluded by OPEN_STATUSES: status={st!r} (need one of {OPEN_STATUSES})",
            )
        )
        if len(sample) >= 10:
            break
    if len(sample) < 10:
        for item in open_not_active:
            ed = item.get("end_date")
            sample.append(
                (
                    item,
                    f"status in OPEN_STATUSES but is_active=False: end_date={ed!r}",
                )
            )
            if len(sample) >= 10:
                break

    log("[filter-diag] sample dropped / excluded (up to 10, reasons):")
    for i, (item, reason) in enumerate(sample[:10], 1):
        title = str(item.get("공고제목") or item.get("title") or "")[:80]
        url = str(item.get("상세URL") or "")[:120]
        st = str(item.get("상태") or "").strip()
        log(
            f"[filter-diag]   [{i}] title={title!r} status={st!r} url={url!r} -> {reason}"
        )

    log(
        "[filter-diag] summary: "
        f"not_in_OPEN_STATUSES={len(not_in_open)} "
        f"OPEN_but_not_is_active={len(open_not_active)}"
    )
    log("[filter-diag] === end diagnostic ===")


# =========================================================
# 오늘 JSON 저장
# =========================================================
def save_today_json(open_announcements: List[Dict[str, Any]]) -> Path:
    path = today_json_path(date.today())
    path.write_text(
        json.dumps(open_announcements, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log(f"[저장] {path.name} ({len(open_announcements)}건)")
    return path


# =========================================================
# 어제 JSON 로드
# =========================================================
def load_yesterday_json() -> List[Dict[str, Any]]:
    y_path = today_json_path(date.today() - timedelta(days=1))

    if not y_path.exists():
        log(f"[로드] 어제 파일 없음: {y_path.name}")
        return []

    try:
        items = json.loads(y_path.read_text(encoding="utf-8"))
        if isinstance(items, list):
            log(f"[로드] 어제 파일 로드: {y_path.name} ({len(items)}건)")
            return items
    except Exception as e:
        log(f"[오류] 어제 파일 로드 실패: {e}")

    return []


# =========================================================
# 신규 공고 찾기
# =========================================================
def find_new_announcements(
    today_items: List[Dict[str, Any]],
    yesterday_items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    yesterday_urls = {
        str(item.get("상세URL") or "").strip()
        for item in yesterday_items
        if isinstance(item, dict)
    }

    new_items: List[Dict[str, Any]] = []
    for item in today_items:
        if not isinstance(item, dict):
            continue
        url = str(item.get("상세URL") or "").strip()
        if url and url not in yesterday_urls:
            new_items.append(item)

    log(f"[비교] 신규 공고 {len(new_items)}건")
    return new_items


# =========================================================
# 신규 JSON 저장
# =========================================================
def save_new_json(new_items: List[Dict[str, Any]]) -> Path:
    path = new_json_path()
    path.write_text(
        json.dumps(new_items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log(f"[저장] {path.name} ({len(new_items)}건)")
    return path


# =========================================================
# 첨부 dedupe
# =========================================================
def dedupe_attachments(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()

    for item in items:
        file_uuid = str(item.get("fileUUID") or "").strip()
        path_num = str(item.get("pathNum") or "6").strip()

        if not file_uuid:
            continue

        key = (file_uuid, path_num)
        if key in seen:
            continue
        seen.add(key)

        out.append({
            "fileUUID": file_uuid,
            "pathNum": path_num,
            "name": str(item.get("name") or "").strip(),
            "size": item.get("size"),
        })

    return out


# =========================================================
# JSON/딕셔너리 내부에서 첨부 레코드 추출
# =========================================================
def extract_attachment_records_from_json(payload: Any) -> List[Dict[str, Any]]:
    raw: List[Dict[str, Any]] = []

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            low_map = {str(k).lower(): v for k, v in x.items()}

            file_uuid = (
                low_map.get("fileuuid")
                or low_map.get("file_uuid")
                or low_map.get("uuid")
                or low_map.get("fileid")
            )
            path_num = (
                low_map.get("pathnum")
                or low_map.get("path_num")
                or low_map.get("path")
                or "6"
            )
            file_name = (
                low_map.get("name")
                or low_map.get("filename")
                or low_map.get("file_name")
                or low_map.get("originfilenm")
                or low_map.get("orgfilenm")
                or low_map.get("originalfilename")
                or ""
            )
            size = low_map.get("size") or low_map.get("filesize") or low_map.get("file_size")

            if file_uuid:
                raw.append({
                    "fileUUID": str(file_uuid).strip(),
                    "pathNum": str(path_num).strip(),
                    "name": str(file_name).strip(),
                    "size": int(size) if str(size).isdigit() else None,
                })

            for v in x.values():
                walk(v)

        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(payload)
    return dedupe_attachments(raw)


# =========================================================
# 첨부파일 목록 조회 - API 시도
# =========================================================
def get_attachments_from_api(sp_seq: str) -> List[Dict[str, Any]]:
    candidates = [
        f"{JBEXPORT_BASE}/common/file/getFileList.do",
        f"{JBEXPORT_BASE}/common/file/selectFileList.do",
        f"{JBEXPORT_BASE}/common/file/getAtchFileList.do",
    ]

    for url in candidates:
        try:
            res = requests.post(
                url,
                data={"spSeq": sp_seq},
                timeout=TIMEOUT,
                verify=False,
            )
            if res.status_code != 200:
                continue

            try:
                payload = res.json()
            except Exception:
                continue

            records = extract_attachment_records_from_json(payload)
            if records:
                return records
        except Exception:
            continue

    return []


# =========================================================
# 첨부파일 목록 조회 - HTML fallback
# =========================================================
def get_attachments_from_html(detail_url: str) -> List[Dict[str, Any]]:
    try:
        res = requests.get(detail_url, timeout=TIMEOUT, verify=False)
        if res.status_code != 200:
            return []
        html = res.text
    except Exception:
        return []

    found: List[Dict[str, Any]] = []

    # 패턴 1: downloadFile.do?...pathNum=...&fileUUID=...
    pattern1 = re.findall(
        r"downloadFile\.do\?[^\"' ]*pathNum=([^&\"' ]+)[^\"' ]*fileUUID=([a-fA-F0-9]+)",
        html,
        re.IGNORECASE,
    )
    for path_num, file_uuid in pattern1:
        found.append({
            "fileUUID": file_uuid,
            "pathNum": path_num,
            "name": "",
        })

    # 패턴 2: fn_fileDown('UUID')
    pattern2 = re.findall(
        r"fn_fileDown\('([a-fA-F0-9]+)'\)",
        html,
        re.IGNORECASE,
    )
    for file_uuid in pattern2:
        found.append({
            "fileUUID": file_uuid,
            "pathNum": "6",
            "name": "",
        })

    return dedupe_attachments(found)


# =========================================================
# 첨부파일 목록 조회 통합
# =========================================================
def get_attachments(sp_seq: str, detail_url: str) -> List[Dict[str, Any]]:
    items = get_attachments_from_api(sp_seq)
    if items:
        log(f"[첨부조회] spSeq={sp_seq} API {len(items)}건")
        return items

    items = get_attachments_from_html(detail_url)
    log(f"[첨부조회] spSeq={sp_seq} HTML {len(items)}건")
    return items


# =========================================================
# 파일명 정리
# =========================================================
def sanitize_filename(name: str) -> str:
    name = str(name or "").strip()
    if not name:
        return ""
    bad = '<>:"/\\|?*'
    for ch in bad:
        name = name.replace(ch, "_")
    return name


def guess_extension(name: str) -> str:
    safe_name = sanitize_filename(name)
    if "." in safe_name:
        ext = safe_name[safe_name.rfind("."):]
        if 1 < len(ext) <= 10:
            return ext
    return ".bin"


# =========================================================
# 다운로드 URL
# =========================================================
def build_download_url(path_num: str, file_uuid: str) -> str:
    query = urllib.parse.urlencode({
        "pathNum": path_num,
        "fileUUID": file_uuid,
    })
    return f"{JBEXPORT_BASE}/downloadFile.do?{query}"


# =========================================================
# 파일 다운로드
# =========================================================
def download_jbexport_file(file_uuid: str, path_num: str, name: str = "") -> Dict[str, Any]:
    download_url = build_download_url(path_num, file_uuid)

    safe_name = sanitize_filename(name)
    ext = guess_extension(safe_name)

    if safe_name:
        save_path = ATTACH_DIR / f"{file_uuid}_{safe_name}"
    else:
        save_path = ATTACH_DIR / f"{file_uuid}{ext}"

    try:
        res = requests.get(download_url, timeout=TIMEOUT, stream=True, verify=False)
        res.raise_for_status()

        with open(save_path, "wb") as f:
            for chunk in res.iter_content(8192):
                if chunk:
                    f.write(chunk)

        size = save_path.stat().st_size
        log(f"[첨부저장] {save_path} ({size} bytes)")
    except Exception as e:
        log(f"[첨부오류] {file_uuid} 다운로드 실패: {e}")
        return {
            "fileUUID": file_uuid,
            "pathNum": path_num,
            "name": safe_name,
            "saved_path": "",
            "size": 0,
        }

    return {
        "fileUUID": file_uuid,
        "pathNum": path_num,
        "name": safe_name or save_path.name,
        "saved_path": str(save_path),
        "size": size,
    }


# =========================================================
# 신규 공고에 첨부 다운로드 붙이기
# =========================================================
def enrich_new_items_with_files(new_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    for item in new_items:
        sp_seq = str(item.get("spSeq") or "").strip()
        detail_url = str(item.get("상세URL") or "").strip()

        if not sp_seq or not detail_url:
            item["files"] = []
            continue

        attachments = get_attachments(sp_seq, detail_url)
        downloaded_files: List[Dict[str, Any]] = []

        for att in attachments:
            file_uuid = str(att.get("fileUUID") or "").strip()
            path_num = str(att.get("pathNum") or "6").strip()
            name = str(att.get("name") or "").strip()

            if not file_uuid:
                continue

            file_info = download_jbexport_file(file_uuid, path_num, name)
            downloaded_files.append(file_info)

        item["files"] = downloaded_files

    return new_items


# =========================================================
# 신규 공고 콘솔 출력
# =========================================================
def print_new_announcements(new_items: List[Dict[str, Any]]) -> None:
    if not new_items:
        print("No new announcements")
        return

    print("===== NEW ANNOUNCEMENTS =====")
    for i, item in enumerate(new_items, 1):
        print(f"{i}. {item.get('공고제목', '')}")
        print(f"   기관: {item.get('기관', '')}")
        print(f"   기간: {item.get('기간', '')}")
        print(f"   상태: {item.get('상태', '')}")
        print(f"   URL: {item.get('상세URL', '')}")

        files = item.get("files") or []
        if files:
            print(f"   첨부: {len(files)}개")
            for f in files:
                print(f"      - {f.get('saved_path', '')} ({f.get('size', 0)} bytes)")
        print("-----------------------------")


# =========================================================
# 실행
# =========================================================
def _load_snapshot_today() -> List[Dict[str, Any]]:
    p = _SNAPSHOT_DATA_DIR / "today.json"
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    return []


def run_daily() -> Dict[str, Any]:
    prev_snapshot = _load_snapshot_today()

    all_items, list_api_raw_rows = fetch_all_announcements()
    open_items = filter_open_announcements(all_items)
    log_filter_stage_diagnosis(list_api_raw_rows, all_items, open_items)

    today_path = save_today_json(open_items)

    new_items = find_new_announcements(open_items, prev_snapshot)

    new_items = enrich_new_items_with_files(new_items)
    new_path = save_new_json(new_items)

    if open_items:
        snap_path = save_today_snapshot(open_items, _SNAPSHOT_DATA_DIR)
        log(f"[스냅샷] {snap_path} (이전 today → yesterday)")
    else:
        log("[스냅샷] 수집 결과가 비어 있어 today.json/yesterday.json 은 갱신하지 않습니다.")

    print_new_announcements(new_items)

    return {
        "date": str(date.today()),
        "new_count": len(new_items),
        "new_items": new_items,
        "today_json": str(today_path),
        "new_json": str(new_path),
    }


if __name__ == "__main__":
    result = run_daily()
    print(json.dumps(result, ensure_ascii=False, indent=2))