# -*- coding: utf-8 -*-
"""
JBEXPORT UI/presenter 전용: DB·병합된 **필드 값**만 ISO(YYYY-MM-DD)로 정규화해 표시.
본문 파싱·임의 날짜 추출은 jbexport_enrich 측에서만 수행한다.
"""
from __future__ import annotations

from pipeline.bizinfo_dates import normalize_one_date


def _g(item: dict, key: str) -> str:
    v = item.get(key)
    if v is None:
        return ""
    return str(v).strip()


def format_jbexport_receipt_period(item: dict) -> tuple[str, str]:
    """receipt_* / apply_* / reception_* / reg_* 만 사용. start_date·end_date 폴백 없음(사업기간과 혼선 방지)."""
    pairs = (
        ("receipt_start", "receipt_end"),
        ("apply_start", "apply_end"),
        ("reception_start", "reception_end"),
        ("reg_start", "reg_end"),
    )
    for a, b in pairs:
        sa, sb = normalize_one_date(_g(item, a)), normalize_one_date(_g(item, b))
        if sa and sb:
            return sa, sb
    rs = normalize_one_date(_g(item, "receipt_start"))
    re_ = normalize_one_date(_g(item, "receipt_end"))
    if rs and re_:
        return rs, re_
    if rs and not re_:
        return rs, "-"
    if not rs and re_:
        return "-", re_
    return "-", "-"


def format_jbexport_biz_period(item: dict) -> tuple[str, str]:
    """biz_*·business_* 스칼라만. HTML·본문은 받지 않음(파싱은 jbexport_enrich → 여기로 필드만 전달)."""
    for a, b in (("biz_start", "biz_end"), ("business_start", "business_end")):
        sa, sb = normalize_one_date(_g(item, a)), normalize_one_date(_g(item, b))
        if sa and sb:
            return sa, sb
    return "-", "-"
