# -*- coding: utf-8 -*-
"""source 추론·기간 파싱 (update_db / validate 공용)."""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

KNOWN_SOURCES = frozenset(
    {
        "jbexport", "bizinfo", "kstartup", "jbba", "jbtp", "kotra", "unknown",
        # 백로그 041 (2026-05-08): 4 source 매핑 누락 fix
        "jbtp_related", "jbbi", "at_global", "kseafood",
    }
)


def infer_source(
    url: str,
    site: str,
    explicit: str,
    *,
    organization: str = "",
    title: str = "",
) -> str:
    """URL·site 우선, organization/title 힌트, 마지막에 명시 source. 빈 문자열 반환 안 함."""
    u = (url or "").lower()
    s = (site or "").lower()
    blob = f"{u} {s}"
    o = (organization or "").strip().lower()
    t = (title or "").strip().lower()
    combo = f"{blob} {o} {t}"

    if "jbexport.or.kr" in u or re.search(r"\bjbexport\b", blob):
        return "jbexport"
    if "bizinfo.go.kr" in u or re.search(r"\bbizinfo\b", blob):
        return "bizinfo"
    if "k-startup.go.kr" in u or "kstartup" in blob or "k-startup" in blob:
        return "kstartup"
    # 백로그 041 (2026-05-08): jbtp_related 보다 먼저 식별 — BBS_0000007 board ID
    # (case-sensitive, raw url 사용. lower 한 u 에는 'BBS_0000007' 가 'bbs_0000007' 이라 url 원문 검사)
    if "jbtp.or.kr" in u and "BBS_0000007" in (url or ""):
        return "jbtp_related"
    if "jbba" in blob:
        return "jbba"
    if "jbtp" in blob:
        return "jbtp"
    if "kotra" in blob:
        return "kotra"
    # 백로그 041: 누락된 4 source URL host 매핑
    if "jif.re.kr" in u:
        return "jbbi"
    if "global.at.or.kr" in u:
        return "at_global"
    if "biz.k-seafoodtrade.kr" in u:
        return "kseafood"

    # URL이 없을 때 organization/title로 출처 추정 (기업마당·전북수출·창업진흥원 등)
    if "기업마당" in o or "기업마당" in t:
        return "bizinfo"
    if "창업진흥원" in o or "창업진흥원" in t or "k-startup" in t.lower():
        return "kstartup"
    if (
        "전북수출" in o
        or "수출통합지원" in o
        or ("전북" in o and "수출" in o)
        or ("전북" in o and "fta" in o)
        or ("전북" in o and "통상" in o)
    ):
        return "jbexport"
    if re.search(r"\bkotra\b", combo):
        return "kotra"
    if "jbba" in combo:
        return "jbba"
    if "jbtp" in combo or "테크노파크" in combo:
        return "jbtp"
    # 백로그 041: organization/title 힌트로 4 source 추정
    if "전북바이오융합" in o or "전북바이오융합" in t:
        return "jbbi"
    if "한국농수산식품유통공사" in o or "한국농수산식품유통공사" in t:
        return "at_global"
    if "한국수산회" in o or "수협중앙회" in o or "한국수산무역협회" in o or "k-seafood" in t:
        return "kseafood"

    ex = (explicit or "").strip().lower()
    if ex in KNOWN_SOURCES:
        return ex
    return "unknown"


def parse_period_from_item(item: Dict[str, Any]) -> Tuple[str, str]:
    """start_date / end_date 보강. period 문자열에서 날짜 추출 시도."""
    sd = str(item.get("start_date") or "").strip()
    ed = str(item.get("end_date") or "").strip()
    period = str(item.get("period") or "").strip()
    if sd and ed:
        return sd, ed
    if not period:
        return sd, ed
    # YYYY-MM-DD ~ YYYY-MM-DD / ~ / -
    pat = re.compile(
        r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})\s*[~\-–]\s*(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})"
    )
    m = pat.search(period.replace(" ", ""))
    if m:
        y1, mo1, d1, y2, mo2, d2 = m.groups()
        return f"{y1}-{int(mo1):02d}-{int(d1):02d}", f"{y2}-{int(mo2):02d}-{int(d2):02d}"
    single = re.findall(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", period)
    if len(single) >= 2 and not sd:
        a, b, c = single[0]
        sd = f"{a}-{int(b):02d}-{int(c):02d}"
        a2, b2, c2 = single[1]
        ed = f"{a2}-{int(b2):02d}-{int(c2):02d}"
    elif len(single) == 1 and not sd:
        a, b, c = single[0]
        sd = f"{a}-{int(b):02d}-{int(c):02d}"
    return sd, ed


def normalize_status(raw: str) -> str:
    t = (raw or "").strip()
    if not t:
        return "확인 필요"
    return t


def normalize_description(item: Dict[str, Any]) -> str:
    d = item.get("description")
    c = item.get("content")
    if d is not None and str(d).strip():
        return str(d).strip()
    if c is not None and str(c).strip():
        return str(c).strip()
    return ""


def canonical_notice_source(source: str) -> str:
    mapping = {
        "bizinfo": "bizinfo",
        "jbexport": "jbexport",
        "kstartup": "kstartup",
    }
    return mapping.get(str(source or "").lower(), str(source or ""))
