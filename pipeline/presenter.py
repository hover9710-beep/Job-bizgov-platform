# -*- coding: utf-8 -*-
"""
표시 dict — 날짜/기관/첨부 등 '표시용' 포맷팅 전담 레이어.

상태(display_status)는 이 모듈에서 계산하지 않는다.
단일 진입점: pipeline.normalize_project.infer_status().
presenter 는 그 결과를 그대로 전달할 뿐, 독자적인 status 로직을 갖지 않는다.
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional, Union

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pipeline import make_mail as m
from pipeline.bizinfo_dates import (
    parse_bizinfo_biz_dates_for_display,
    parse_bizinfo_receipt_dates_for_display,
)
from pipeline.normalize_project import infer_status
from pipeline.project_quality import canonical_notice_source
from pipeline.jbexport_display import format_jbexport_biz_period, format_jbexport_receipt_period

BAD_ORG_TOKENS = frozenset(
    {
        "금융",
        "창업",
        "기술",
        "인력",
        "경영",
        "수출",
        "내수",
        "확인필요",
        "확인 필요",
        "보기",
        "기업마당",
        "지원사업",
        "모집공고",
        "참여기업",
        "공고",
        "-",
    }
)

_ORG_FIELD_ORDER = (
    "organization",
    "executing_agency",
    "agency",
    "provider",
    "ministry",
    "department",
    "support_org",
    "organization_name",
)


def _collect_dates_in_order(text: str) -> list:
    import re

    return re.findall(r"\d{4}-\d{2}-\d{2}", text or "")

def _normalize_spaces(s: str) -> str:
    return " ".join(s.split())


def _is_bad_org_token(s: str) -> bool:
    t = (s or "").strip()
    return not t or t in BAD_ORG_TOKENS


def persisted_source_key(item: dict) -> str:
    """DB 스냅샷(_db_source_snapshot) 최우선 → source. 파서 분기 전용. URL 휴리스틱 없음."""
    if "_db_source_snapshot" in item:
        s = str(item.get("_db_source_snapshot") or "").strip().lower()
        if s:
            return s
    return str(item.get("source") or "").strip().lower()


def _fallback_org_by_source(item: dict) -> str:
    src = persisted_source_key(item)
    if src == "jbexport":
        return "전북수출통합지원시스템"
    if src == "bizinfo":
        return "기업마당"
    blob = f"{item.get('_source') or ''} {item.get('source') or ''}".lower()
    if "jbexport" in blob:
        return "전북수출통합지원시스템"
    if "bizinfo" in blob or "기업마당" in blob:
        return "기업마당"
    return "-"


def clean_organization(item: dict) -> str:
    for f in _ORG_FIELD_ORDER:
        v = item.get(f)
        if v is None:
            continue
        s = str(v).strip()
        if s and not _is_bad_org_token(s):
            return _normalize_spaces(s)
    return _fallback_org_by_source(item)


def _source_badge(item: dict) -> str:
    """UI 배지용. DB 스냅샷 우선 → 비어 있으면 canonical만( URL 휴리스틱으로 jbexport 덮어쓰지 않음)."""
    s = persisted_source_key(item)
    if s in ("jbexport", "bizinfo", "jbba", "jbtp", "kotra"):
        return s
    if s:
        return s
    c = str(canonical_notice_source(dict(item)) or "").strip().lower()
    if c in ("jbexport", "bizinfo", "jbba", "jbtp", "kotra"):
        return c
    return "기타"


def _parse_iso(s: str) -> Optional[date]:
    if not s or len(s) < 10:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _receipt_value_to_date(
    x: Union[str, date, datetime, None],
) -> Optional[date]:
    """접수기간 문자열·date → date. biz_* / raw status는 여기 넣지 않음."""
    if x is None:
        return None
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    s = str(x).strip()
    if not s or s == "-":
        return None
    chunk = s[:10]
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(chunk, fmt).date()
        except Exception:
            continue
    return None


def _norm_one_date_val(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    if not s or s in ("-", "확인필요", "확인 필요"):
        return None
    dates = _collect_dates_in_order(s)
    if dates:
        return dates[0][:10]
    return None


def extract_receipt_period(item: dict) -> tuple[str, str]:
    """접수(신청) 기간. source=='bizinfo'|'jbexport' 는 각 전용 파서만. 그 외 generic."""
    src = persisted_source_key(item)

    def _pair_hit(
        pairs: tuple[tuple[str, str], ...],
    ) -> tuple[str, str] | None:
        for a, b in pairs:
            va, vb = item.get(a), item.get(b)
            if va is None or vb is None:
                continue
            if not str(va).strip() or not str(vb).strip():
                continue
            sa = _norm_one_date_val(va)
            sb = _norm_one_date_val(vb)
            if sa and sb:
                return sa, sb
        return None

    def _partial_receipt() -> tuple[str, str] | None:
        rpa = _norm_one_date_val(item.get("receipt_start"))
        rpb = item.get("receipt_end")
        rpe = _norm_one_date_val(rpb) if rpb is not None and str(rpb).strip() else None
        if rpa and rpe:
            return rpa, rpe
        if rpa and not rpe:
            return rpa, "-"
        if not rpa and rpe:
            return "-", rpe
        return None

    if src == "bizinfo":
        pr = parse_bizinfo_receipt_dates_for_display(item)
        if isinstance(pr, (list, tuple)): pr = dict(enumerate(pr))
        sd, ed = (pr.get("start_date") or "").strip(), (pr.get("end_date") or "").strip()
        if sd and ed:
            return sd, ed
        return "-", "-"

    if src == "jbexport":
        return format_jbexport_receipt_period(item)

    # 그 외 소스: 구조화 필드 쌍 + 일측 접수
    hit = _pair_hit(
        (
            ("receipt_start", "receipt_end"),
            ("apply_start", "apply_end"),
            ("reception_start", "reception_end"),
            ("reg_start", "reg_end"),
            ("effective_start_date", "effective_end_date"),
        )
    )
    if hit:
        return hit
    partial = _partial_receipt()
    if partial:
        return partial
    return "-", "-"


def extract_biz_period(item: dict) -> tuple[str, str]:
    """사업기간 — source 분기만 사용."""
    src = persisted_source_key(item)

    if src == "bizinfo":
        pb = parse_bizinfo_biz_dates_for_display(item)
        sd, ed = (pb.get("start_date") or "").strip(), (pb.get("end_date") or "").strip()
        if sd and ed:
            return sd, ed
        return "-", "-"

    if src == "jbexport":
        return format_jbexport_biz_period(item)

    for a, b in (
        ("biz_start", "biz_end"),
        ("business_start", "business_end"),
    ):
        va, vb = item.get(a), item.get(b)
        if va is None or vb is None:
            continue
        if not str(va).strip() or not str(vb).strip():
            continue
        sa = _norm_one_date_val(va)
        sb = _norm_one_date_val(vb)
        if sa and sb:
            return sa, sb

    return "-", "-"


def extract_registered_at(item: dict) -> str:
    """등록·게시 등 참고용 (상태 판정에 사용하지 않음)."""
    for k in (
        "registered_at",
        "created_at",
        "posted_at",
        "published_at",
        "collected_at",
        "reg_date",
        "등록일",
        "postedAt",
        "createdAt",
    ):
        v = _norm_one_date_val(item.get(k))
        if v:
            return v
    if persisted_source_key(item) == "bizinfo":
        v = _norm_one_date_val(item.get("date"))
        if v:
            return v
    return "-"


def receipt_parser_label(item: dict) -> str:
    """extract_receipt_period 와 동일 분기 라벨(감사 로그용)."""
    src = persisted_source_key(item)
    if src == "bizinfo":
        return "bizinfo_parser"
    if src == "jbexport":
        return "jbexport_parser"
    return "generic"


def compute_is_ending_soon_receipt(
    display_status: str,
    ds: str,
    de: str,
    today: Optional[date] = None,
) -> bool:
    if display_status != "접수중":
        return False
    if not de or de == "-":
        return False
    ree = _receipt_value_to_date(de)
    if not ree:
        return False
    t = today or date.today()
    d = (ree - t).days
    return 0 <= d <= 7


def normalize_attachments_list(item: dict) -> list[dict[str, str]]:
    keys = (
        "attachments",
        "files",
        "file_list",
        "attach_files",
        "file_urls",
    )
    result: list[dict[str, str]] = []
    for k in keys:
        raw = item.get(k)
        if raw is None:
            continue
        if isinstance(raw, str):
            if raw.strip():
                result.append({"name": raw.strip(), "url": ""})
            continue
        if isinstance(raw, dict):
            for name, url in raw.items():
                result.append({"name": str(name), "url": str(url or "")})
            if result:
                break
            continue
        if not isinstance(raw, list):
            continue
        for f in raw:
            if isinstance(f, dict):
                name = (
                    f.get("name")
                    or f.get("filename")
                    or f.get("title")
                    or "첨부파일"
                )
                url = (
                    f.get("url")
                    or f.get("href")
                    or f.get("download_url")
                    or ""
                )
            elif isinstance(f, str):
                name = f
                url = ""
            else:
                continue
            name = str(name)
            url = str(url or "")
            ext = name.split(".")[-1].lower() if "." in name else ""
            result.append({"name": name, "url": url, "ext": ext})
        if result:
            break
    out: list[dict[str, str]] = []
    for r in result:
        out.append(
            {
                "name": r.get("name", ""),
                "url": r.get("url", ""),
                "ext": r.get("ext", ""),
            }
        )
    return out


def build_ai_summary_from_display(item: dict) -> str:
    org = str(item.get("organization") or "기관 정보 없음")
    title = str(item.get("title") or "제목 없음")
    st = str(item.get("display_status") or "확인 필요")
    ds = item.get("display_receipt_start") or item.get("display_start_date") or "-"
    de = item.get("display_receipt_end") or item.get("display_end_date") or "-"
    if ds == "-" or de == "-":
        period = "접수기간 확인 필요"
    else:
        period = f"{ds} ~ {de}"
    return (
        f"{org}의 '{title}' 공고입니다. 현재 상태는 {st}이며 접수기간은 {period} 입니다."
    )


def normalize_display_item(item: dict) -> dict:
    if isinstance(item, (list, tuple)):
        item = {i: v for i, v in enumerate(item)}
    work = dict(item)
    orig_source = str(item.get("source") or "").strip()
    snap0 = str(item.get("_db_source_snapshot") or orig_source).strip().lower()
    work["_db_source_snapshot"] = snap0
    # DB에 저장된 source는 canonical 추론으로 덮어쓰지 않음(파서 분기·표시 일관성).
    work["source"] = orig_source
    canon_src = canonical_notice_source(dict(item))
    work["_source"] = (orig_source or canon_src or "unknown").upper()

    title = m.get_field(work, "title", "사업명", "공고명", "제목")
    organization = clean_organization(work)
    src_badge = _source_badge(work)
    raw_status = m.get_field(
        work,
        "raw_status",
        "status",
        "state",
        "progress_status",
        "progress",
        "condition",
        "apply_status",
    )
    raw_start_date = str(work.get("start_date") or "").strip()
    raw_end_date = str(work.get("end_date") or "").strip()

    display_receipt_start, display_receipt_end = extract_receipt_period(work)
    display_biz_start, display_biz_end = extract_biz_period(work)
    display_registered_at = extract_registered_at(work)

    # status 는 presenter 가 계산하지 않는다 — 단일 진입점(infer_status) 위임.
    period_text = str(work.get("period_text") or "").strip()
    sd_for_status = str(work.get("start_date") or "").strip()
    ed_for_status = str(work.get("end_date") or "").strip()
    today_iso = date.today().isoformat()
    display_status = infer_status(period_text, sd_for_status, ed_for_status, today_iso)

    is_ending_soon = compute_is_ending_soon_receipt(
        display_status, display_receipt_start, display_receipt_end
    )

    url = m.get_field(work, "url", "detail_url", "link", "href")
    attachments_list = normalize_attachments_list(work)
    has_attachments = bool(attachments_list)

    out = {
        "title": title,
        "organization": organization,
        "source": orig_source,
        "canonical_source": canon_src,
        "db_source_snapshot": snap0,
        "source_badge": src_badge,
        "display_status": display_status,
        "display_receipt_start": display_receipt_start,
        "display_receipt_end": display_receipt_end,
        "display_biz_start": display_biz_start,
        "display_biz_end": display_biz_end,
        "display_registered_at": display_registered_at,
        "display_start_date": display_receipt_start,
        "display_end_date": display_receipt_end,
        "url": url,
        "attachments_list": attachments_list,
        "has_attachments": has_attachments,
        "ai_summary": "",
        "raw_status": raw_status,
        "raw_start_date": raw_start_date,
        "raw_end_date": raw_end_date,
        "is_ending_soon": is_ending_soon,
    }
    merged = dict(work)
    merged.update(out)
    merged["ai_summary"] = build_ai_summary_from_display(merged)
    return merged


def normalize_display_items(items: list[dict]) -> list[dict]:
    return [normalize_display_item(dict(x) if not isinstance(x, dict) else x) for x in items]
