# -*- coding: utf-8 -*-
"""
BIZINFO row → canonical start_date / end_date (YYYY-MM-DD).

Used by merge_sources (data/all_sites.json). Does not alter crawl filtering.
"""
from __future__ import annotations

import re
from datetime import date as date_cls
from typing import Any, Dict, List, Optional, Tuple

# Order: structured single fields and period blobs
_BIZINFO_PERIOD_KEYS: Tuple[str, ...] = (
    "period",
    "support_period",
    "apply_period",
    "reception_period",
    "reqstBeginEndDe",
    "접수기간",
    "사업기간",
    "공고기간",
    "신청기간",
    "모집기간",
    "기간",
    "rcptPd",
    "rcpt_period",
    "receiptPeriod",
    "applyPeriod",
    "dateRange",
)

_START_KEYS: Tuple[str, ...] = (
    "start_date",
    "startDate",
    "strtDt",
    "beginDt",
    "pbancBgngYmd",
    "bizPrdBgngYmd",
    "s_date",
    "start",
)

_END_KEYS: Tuple[str, ...] = (
    "end_date",
    "endDate",
    "closeDt",
    "deadline",
    "pbancEndYmd",
    "bizPrdEndYmd",
    "e_date",
    "end",
    "close",
)

_TEXT_FALLBACK_KEYS: Tuple[str, ...] = (
    "description",
    "summary",
    "content",
    "body",
    "title",
)

_DATE_TOKEN_RE = re.compile(
    r"(\d{4})\s*[.\-/년]?\s*(\d{1,2})\s*[.\-/월]?\s*(\d{1,2})(?:\s*일)?"
)
_DATE_COMPACT8_RE = re.compile(r"(?<!\d)(\d{8})(?!\d)")
_RANGE_SEP_RE = re.compile(r"\s*[~～\-–—至]\s*")


def _valid_iso(s: str) -> bool:
    """Reject garbage like 1527-20-26 from mis-parsed digits."""
    if not s or len(s) != 10 or s[4] != "-" or s[7] != "-":
        return False
    try:
        y, m, d = int(s[:4]), int(s[5:7]), int(s[8:10])
        if not (1990 <= y <= 2100):
            return False
        date_cls(y, m, d)
        return True
    except (ValueError, IndexError):
        return False


def _sanitize_iso(token: str) -> str:
    return token if _valid_iso(token) else ""


def _junk_text_field(s: str) -> bool:
    """Skip list mis-columns like '447', '1527' stored as description."""
    t = str(s or "").strip()
    if not t:
        return True
    if t.isdigit() and len(t) <= 6:
        return True
    return False


def normalize_one_date(raw: Any) -> str:
    """Single value → YYYY-MM-DD or ''. Supports YYYYMMDD and common separators."""
    if raw is None:
        return ""
    s = str(raw).strip()
    if not s:
        return ""

    m8 = _DATE_COMPACT8_RE.search(s.replace(" ", ""))
    if m8:
        d = m8.group(1)
        if len(d) == 8 and d.isdigit():
            y, mo, da = d[:4], d[4:6], d[6:8]
            try:
                if 1 <= int(mo) <= 12 and 1 <= int(da) <= 31:
                    return _sanitize_iso(f"{y}-{mo}-{da}")
            except ValueError:
                pass

    m = _DATE_TOKEN_RE.search(s)
    if m:
        y, mo, d = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
        cand = f"{y}-{mo}-{d}"
        return _sanitize_iso(cand)
    return ""


def _all_iso_dates_in_text(text: str) -> List[str]:
    """Collect unique YYYY-MM-DD tokens in order of appearance."""
    out: List[str] = []
    seen = set()
    for m in _DATE_TOKEN_RE.finditer(str(text or "")):
        y, mo, d = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
        iso = _sanitize_iso(f"{y}-{mo}-{d}")
        if not iso:
            continue
        if iso not in seen:
            seen.add(iso)
            out.append(iso)
    flat = str(text or "").replace(" ", "")
    for m in _DATE_COMPACT8_RE.finditer(flat):
        d = m.group(1)
        if len(d) == 8 and d.isdigit():
            iso = _sanitize_iso(f"{d[:4]}-{d[4:6]}-{d[6:8]}")
            if not iso:
                continue
            if iso not in seen:
                seen.add(iso)
                out.append(iso)
    return out


def extract_date_range(text: str) -> Tuple[str, str]:
    """
    Parse (start_date, end_date) from free text.
    Prefers explicit ranges; otherwise first two distinct dates.
    """
    raw = str(text or "")
    if not raw.strip():
        return "", ""

    work = (
        raw.replace("～", "~")
        .replace("–", "~")
        .replace("—", "~")
        .replace("至", "~")
    )

    # Two full dates around ~ - –
    m = re.search(
        r"(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})\s*[~\-–]\s*(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})",
        work,
    )
    if m:
        a, b = normalize_one_date(m.group(1)), normalize_one_date(m.group(2))
        return a, b

    m = re.search(
        r"(\d{8})\s*[~\-–]\s*(\d{8})",
        work.replace(" ", "").replace(".", ""),
    )
    if m:
        a, b = normalize_one_date(m.group(1)), normalize_one_date(m.group(2))
        if a and b:
            return a, b

    if "~" in work:
        left, right = work.split("~", 1)
        ls, rs = normalize_one_date(left), normalize_one_date(right)
        if ls or rs:
            return ls, rs

    for sep in ("부터", "至"):
        if sep in work:
            parts = work.split(sep, 1)
            if len(parts) == 2:
                a, b = parts[0].strip(), parts[1].strip()
                if sep == "부터" and "까지" in b:
                    b = b.split("까지", 1)[0].strip()
                sa, sb = normalize_one_date(a), normalize_one_date(b)
                if sa or sb:
                    return sa, sb

    dates = _all_iso_dates_in_text(work)
    if len(dates) >= 2:
        return dates[0], dates[1]
    if len(dates) == 1:
        return dates[0], ""
    return "", ""


def _get(item: Dict[str, Any], key: str) -> str:
    v = item.get(key)
    if v is None:
        return ""
    return str(v).strip()


def _dates_result(sd: str, ed: str, period_text: str = "") -> Dict[str, str]:
    a, b = _sanitize_iso(sd), _sanitize_iso(ed)
    if a and b:
        try:
            if date_cls.fromisoformat(a) > date_cls.fromisoformat(b):
                a, b = b, a
        except ValueError:
            pass
    return {"start_date": a, "end_date": b, "period_text": period_text or ""}


# period_text 우선순위 (접수기간 > 신청기간 > 모집기간 > 사업기간 > 공고기간 > 기간).
# 가공하지 않고 첫 매칭 라벨의 raw 텍스트를 그대로 저장하기 위한 순서.
_PERIOD_TEXT_LABEL_ORDER: Tuple[str, ...] = (
    "접수기간",
    "신청기간",
    "모집기간",
    "사업기간",
    "공고기간",
    "기간",
)


def _pick_period_text(item: Dict[str, Any]) -> str:
    """우선순위 라벨로 매칭된 첫 번째 raw 텍스트. 없으면 빈 문자열."""
    for label in _PERIOD_TEXT_LABEL_ORDER:
        v = item.get(label)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return ""


def parse_bizinfo_dates(item: Dict[str, Any]) -> Dict[str, str]:
    """
    Return:
      {
        "start_date": "YYYY-MM-DD" or "",
        "end_date":   "YYYY-MM-DD" or "",
        "period_text": raw label text or "",
      }
    """
    period_text = _pick_period_text(item)
    sd, ed = "", ""

    # Paired structured YMD (API-style)
    for sk, ek in (
        ("pbancBgngYmd", "pbancEndYmd"),
        ("bizPrdBgngYmd", "bizPrdEndYmd"),
        ("startDate", "endDate"),
        ("start_date", "end_date"),
    ):
        a, b = normalize_one_date(_get(item, sk)), normalize_one_date(_get(item, ek))
        if a or b:
            sd, ed = a or sd, b or ed
            if sd or ed:
                return _dates_result(sd, ed, period_text)

    # Unpaired start/end columns
    for k in _START_KEYS:
        v = normalize_one_date(_get(item, k))
        if v:
            sd = v
            break
    for k in _END_KEYS:
        v = normalize_one_date(_get(item, k))
        if v:
            ed = v
            break
    if sd and ed:
        return _dates_result(sd, ed, period_text)

    # Period-like blobs (single field may contain range)
    for k in _BIZINFO_PERIOD_KEYS:
        blob = _get(item, k)
        if not blob:
            continue
        ps, pe = extract_date_range(blob)
        if ps:
            sd = sd or ps
        if pe:
            ed = ed or pe
        if sd and ed:
            return _dates_result(sd, ed, period_text)

    # List column "date" (often 등록일/게시일): one value → start_date only unless range
    list_date = _get(item, "date")
    if list_date:
        ps, pe = extract_date_range(list_date)
        if ps and pe:
            sd, ed = sd or ps, ed or pe
        elif ps and not pe:
            sd = sd or ps
        elif pe:
            sd = sd or pe
        else:
            one = normalize_one_date(list_date)
            if one:
                sd = sd or one

    # Text fallbacks: title + description + body (skip numeric junk descriptions)
    blob_parts: List[str] = []
    for k in _TEXT_FALLBACK_KEYS:
        v = _get(item, k)
        if not v:
            continue
        if k == "description" and _junk_text_field(v):
            continue
        blob_parts.append(v)
    blob = " ".join(blob_parts)
    if blob.strip():
        ps, pe = extract_date_range(blob)
        if ps:
            sd = sd or ps
        if pe:
            ed = ed or pe

    return _dates_result(sd, ed, period_text)


def first_raw_period_preview(item: Dict[str, Any]) -> str:
    """First non-empty period-like field for debug logs."""
    for k in ("raw_period", "period", "date", *_BIZINFO_PERIOD_KEYS, *_START_KEYS, *_END_KEYS):
        v = _get(item, k)
        if v:
            return v[:120]
    return ""


def parse_bizinfo_biz_dates_for_display(item: dict) -> dict:
    return {"biz_start": item.get("biz_start", ""), "biz_end": item.get("biz_end", "")}


def parse_bizinfo_receipt_dates_for_display(item: dict) -> dict:
    return {
        "receipt_start": item.get("receipt_start") or item.get("start_date", ""),
        "receipt_end": item.get("receipt_end") or item.get("end_date", ""),
    }


# 접수기간(reception) 전용 키 집합. 사업기간 키는 일부러 제외해야 혼선이 없음.
_RECEIPT_PAIRED_KEYS: Tuple[Tuple[str, str], ...] = (
    ("pbancBgngYmd", "pbancEndYmd"),
)
_RECEIPT_PERIOD_KEYS: Tuple[str, ...] = (
    "reqstBeginEndDe",
    "rcptPd",
    "rcpt_period",
    "reception_period",
    "apply_period",
    "applyPeriod",
    "receiptPeriod",
    "접수기간",
    "신청기간",
    "모집기간",
)

# 사업기간(support/biz period) 전용 키 집합.
_BIZ_PAIRED_KEYS: Tuple[Tuple[str, str], ...] = (
    ("bizPrdBgngYmd", "bizPrdEndYmd"),
)
_BIZ_PERIOD_KEYS: Tuple[str, ...] = (
    "support_period",
    "biz_period",
    "bizPeriod",
    "사업기간",
    "지원기간",
    "운영기간",
)


def _parse_scoped_dates(
    item: Dict[str, Any],
    paired_keys: Tuple[Tuple[str, str], ...],
    period_keys: Tuple[str, ...],
) -> Dict[str, str]:
    """키 범위를 한정한 bizinfo 날짜 파서. 범위 내에서 못 찾으면 빈 dict 반환."""
    sd, ed = "", ""
    for sk, ek in paired_keys:
        a = normalize_one_date(_get(item, sk))
        b = normalize_one_date(_get(item, ek))
        if a or b:
            sd, ed = a or sd, b or ed
            if sd and ed:
                return _dates_result(sd, ed)
    for k in period_keys:
        blob = _get(item, k)
        if not blob:
            continue
        ps, pe = extract_date_range(blob)
        if ps:
            sd = sd or ps
        if pe:
            ed = ed or pe
        if sd and ed:
            return _dates_result(sd, ed)
    if sd or ed:
        return _dates_result(sd, ed)
    return {"start_date": "", "end_date": ""}


def parse_bizinfo_receipt_dates(item: Dict[str, Any]) -> Dict[str, str]:
    """
    접수기간(reception period) 파서.
    먼저 접수 전용 키만 탐색하고, 비면 generic parse_bizinfo_dates 로 폴백.
    반환: {"start_date": "YYYY-MM-DD" or "", "end_date": "YYYY-MM-DD" or ""}
    """
    pre = (
        str(item.get("receipt_start") or "").strip(),
        str(item.get("receipt_end") or "").strip(),
    )
    if pre[0] or pre[1]:
        sd = normalize_one_date(pre[0]) or pre[0]
        ed = normalize_one_date(pre[1]) or pre[1]
        if sd or ed:
            return _dates_result(sd, ed)

    scoped = _parse_scoped_dates(item, _RECEIPT_PAIRED_KEYS, _RECEIPT_PERIOD_KEYS)
    if scoped["start_date"] or scoped["end_date"]:
        return scoped
    return parse_bizinfo_dates(item)


def parse_bizinfo_biz_dates(item: Dict[str, Any]) -> Dict[str, str]:
    """
    사업기간(support period) 파서.
    사업 전용 키 범위만 탐색. 접수기간과 분리되어야 하므로 generic 폴백 없음.
    반환: {"start_date": "...", "end_date": "..."} (없으면 빈 문자열)
    """
    pre = (
        str(item.get("biz_start") or "").strip(),
        str(item.get("biz_end") or "").strip(),
    )
    if pre[0] or pre[1]:
        sd = normalize_one_date(pre[0]) or pre[0]
        ed = normalize_one_date(pre[1]) or pre[1]
        if sd or ed:
            return _dates_result(sd, ed)
    return _parse_scoped_dates(item, _BIZ_PAIRED_KEYS, _BIZ_PERIOD_KEYS)


def parse_date_range(dates: List[str]) -> Tuple[str, str]:
    """
    날짜 리스트를 받아 (start, end) 튜플 반환.

    정책
    - 유효한 YYYY-MM-DD (또는 YYYYMMDD / 구분자 있는 표기) 만 사용.
    - 0개: ("", "")
    - 1개: (해당 값, 해당 값)  ← 단일 일자 공고(접수=마감 같은 날) 케이스 보존
    - 2개 이상: (min, max)      ← 등록일·마감일 순서 뒤바뀜 자동 교정

    connector 계열에서 "추출된 날짜 개수가 2~3개" 인 소스(kstartup 등) 통일용.
    소스별 라벨 매칭이 필요한 bizinfo 같은 경우에는 parse_bizinfo_dates 사용.
    """
    cleaned: List[str] = []
    for raw in dates or []:
        iso = _sanitize_iso(str(raw).strip()) or normalize_one_date(raw)
        iso = _sanitize_iso(iso)
        if iso and iso not in cleaned:
            cleaned.append(iso)
    if not cleaned:
        return "", ""
    if len(cleaned) == 1:
        return cleaned[0], cleaned[0]
    return min(cleaned), max(cleaned)
