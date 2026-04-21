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


def _dates_result(sd: str, ed: str) -> Dict[str, str]:
    a, b = _sanitize_iso(sd), _sanitize_iso(ed)
    if a and b:
        try:
            if date_cls.fromisoformat(a) > date_cls.fromisoformat(b):
                a, b = b, a
        except ValueError:
            pass
    return {"start_date": a, "end_date": b}


def parse_bizinfo_dates(item: Dict[str, Any]) -> Dict[str, str]:
    """
    Return:
      { "start_date": "YYYY-MM-DD" or "", "end_date": "YYYY-MM-DD" or "" }
    """
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
                return _dates_result(sd, ed)

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
        return _dates_result(sd, ed)

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
            return _dates_result(sd, ed)

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

    return _dates_result(sd, ed)


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
