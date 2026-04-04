"""
공고 필드 표준화: 기간(start_date, end_date), 상태(status).

merge_jb / 크롤 결과 JSON에서 키 이름이 달라도 동일 규칙으로 맞춤.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

_DATE_RE = re.compile(
    r"(\d{4})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})",
    re.UNICODE,
)
_DATE_COMPACT_RE = re.compile(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})")
_TWO_DATES_RE = re.compile(
    r"(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})\s*[-~～–—]\s*(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})",
)


def _pick(item: Dict[str, Any], keys: Iterable[str], default: str = "") -> str:
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def _token_to_iso_date(token: str) -> str:
    """가능하면 YYYY-MM-DD 로 정규화, 아니면 trim 만."""
    s = str(token or "").strip()
    if not s:
        return ""
    m = _DATE_COMPACT_RE.search(s) or _DATE_RE.search(s)
    if not m:
        return s
    y, mo, d = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
    return f"{y}-{mo}-{d}"


def _split_period_string(raw: str) -> Tuple[str, str]:
    """한 줄 기간 문자열을 시작/종료로 분리."""
    s = str(raw or "").strip()
    if not s:
        return "", ""

    # 공백 정규화
    work = s.replace("～", "~").replace("–", "~").replace("—", "~")

    m2 = _TWO_DATES_RE.search(work)
    if m2:
        return _token_to_iso_date(m2.group(1)), _token_to_iso_date(m2.group(2))

    # ~ 우선
    if "~" in work:
        left, right = work.split("~", 1)
        return _token_to_iso_date(left), _token_to_iso_date(right)

    for d in ("至", "부터"):
        if d in work:
            parts = work.split(d, 1)
            if len(parts) == 2:
                a, b = parts[0].strip(), parts[1].strip()
                if d == "부터" and "까지" in b:
                    b = b.split("까지", 1)[0].strip()
                return _token_to_iso_date(a), _token_to_iso_date(b)

    # 단일 날짜만
    one = _token_to_iso_date(work)
    if one and re.match(r"^\d{4}-\d{2}-\d{2}$", one):
        return one, ""

    return "", ""


def _two_unique_dates_from_text(text: str) -> Tuple[str, str]:
    """본문에서 YYYY-MM-DD 형태 날짜를 순서대로 최대 2개."""
    flat = re.findall(r"\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2}", str(text or ""))
    uniq: List[str] = []
    for d in flat:
        if d not in uniq:
            uniq.append(d)
        if len(uniq) >= 2:
            break
    if len(uniq) >= 2:
        return _token_to_iso_date(uniq[0]), _token_to_iso_date(uniq[1])
    if len(uniq) == 1:
        return _token_to_iso_date(uniq[0]), ""
    return "", ""


def extract_period_line_from_text(text: str) -> str:
    """본문에서 접수기간 등 라벨 뒤 한 줄 추출."""
    raw = str(text or "")
    if not raw.strip():
        return ""
    patterns = (
        r"(?:접수기간|신청기간|공고기간|모집기간|사업기간)\s*[:：]\s*([^\n\r]+)",
        r"(?:접수)\s*[:：]\s*([^\n\r]+)",
    )
    for pat in patterns:
        m = re.search(pat, raw)
        if m:
            return m.group(1).strip()
    return ""


def parse_dates_from_item(item: Dict[str, Any], body_fallback: str = "") -> Tuple[str, str, str]:
    """
    반환: (start_date, end_date, period_raw_원문)
    period_raw 는 로그/디버그용.
    """
    sd = _pick(
        item,
        (
            "start_date",
            "startDate",
            "strtDt",
            "beginDt",
            "begin",
            "s_date",
            "start",
        ),
    )
    ed = _pick(
        item,
        (
            "end_date",
            "endDate",
            "closeDt",
            "deadline",
            "endDt",
            "e_date",
            "end",
            "close",
        ),
    )
    period_raw = _pick(
        item,
        (
            "period",
            "기간",
            "접수기간",
            "신청기간",
            "공고기간",
            "사업기간",
            "모집기간",
            "rcptPd",
            "rcpt_period",
            "receiptPeriod",
            "applyPeriod",
            "dateRange",
        ),
    )

    if sd and ed:
        return _token_to_iso_date(sd), _token_to_iso_date(ed), period_raw or ""

    if not period_raw and body_fallback:
        period_raw = extract_period_line_from_text(body_fallback)

    if period_raw:
        ps, pe = _split_period_string(period_raw)
        if not sd and ps:
            sd = ps
        if not ed and pe:
            ed = pe

    if (not sd or not ed) and body_fallback:
        bs, be = _two_unique_dates_from_text(body_fallback)
        if not sd and bs:
            sd = bs
        if not ed and be:
            ed = be

    return _token_to_iso_date(sd), _token_to_iso_date(ed), period_raw


def normalize_status(raw: str) -> str:
    """
    - 진행 / 접수중 / 모집중 → 진행
    - 마감 / 종료 / 접수마감 → 마감
    - 없거나 판별 불가 → 확인 필요
    """
    t = str(raw or "").strip()
    if not t:
        return "확인 필요"

    closed_kw = (
        "마감",
        "종료",
        "접수마감",
        "공고종료",
        "모집종료",
        "신청마감",
        "deadline",
        "closed",
        "end",
    )
    open_kw = (
        "접수중",
        "접수 중",
        "모집중",
        "모집 중",
        "공고중",
        "공고 중",
        "진행",
        "진행중",
        "진행 중",
        "신청중",
        "open",
        "ongoing",
    )

    tl = t.lower()
    for w in closed_kw:
        if w in t:
            return "마감"
        if w.isascii() and len(w) >= 3 and w in tl:
            return "마감"
    for w in open_kw:
        if w in t:
            return "진행"
        if w.isascii() and len(w) >= 3 and w in tl:
            return "진행"

    return "확인 필요"


def pick_status_raw(item: Dict[str, Any], body_fallback: str = "") -> str:
    s = _pick(
        item,
        (
            "status",
            "상태",
            "STS_TXT",
            "progressStatus",
            "ingYnNm",
            "공고상태",
            "진행상태",
            "접수상태",
            "prgrsStts",
        ),
    )
    if s:
        return s
    if body_fallback:
        m = re.search(
            r"(?:진행상태|공고상태|접수상태|상태)\s*[:：]\s*([^\n\r]+)",
            body_fallback,
        )
        if m:
            return m.group(1).strip()
    return ""


def enrich_dates_and_status(
    item: Dict[str, Any],
    *,
    body_for_fallback: str = "",
    period_unparsed_log: Optional[List[str]] = None,
) -> Dict[str, str]:
    """
    item 은 원본 dict. 반환: start_date, end_date, status(정규화됨).
    """
    body = body_for_fallback or _pick(
        item, ("description", "content", "body", "지원내용", "본문", "summary")
    )
    sd, ed, period_raw = parse_dates_from_item(item, body_fallback=body)

    # 기간 문자열은 있는데 시작·마감을 끝내 못 찾은 경우만 원문 로그
    if period_raw and not sd and not ed and period_unparsed_log is not None:
        snippet = period_raw.replace("\n", " ")[:120]
        period_unparsed_log.append(snippet)

    status_raw = pick_status_raw(item, body_fallback=body)
    status = normalize_status(status_raw)

    return {
        "start_date": sd,
        "end_date": ed,
        "status": status,
    }
