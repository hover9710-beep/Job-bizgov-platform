# -*- coding: utf-8 -*-
"""
pipeline/make_mail.py
메일 본문 생성 — 날짜 기준: 진행 중 / 신규(7일) / 곧 마감(7일)
"""

import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

_DATE_YMD = re.compile(r"\d{4}-\d{2}-\d{2}")
_RE_KO_FULL = re.compile(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일")
_RE_KO_YM = re.compile(r"(\d{4})년\s*(\d{1,2})월(?!\s*\d{1,2}일)")
_RE_DOT = re.compile(r"\d{4}\.\d{2}\.\d{2}")

today = datetime.today().date()

ALL_FILE = Path("data/all_sites.json")
NEW_FILE = Path("data/new.json")
OUT_FILE = Path("data/mail/mail_body.txt")

# 전체 접수중 섹션 가독성 (기관당 / 전체 상한)
# 기관당이 너무 낮으면 기관 수·소형 기관 한도 때문에 전체 상한(60)에 못 미침 (예: 8×9 - 소형 = 53)
# JBEXPORT: is_active 에서 status(open 키워드)만 사용. 그 외 소스는 마감일(_effective_end_date_str) 기준.
SEC_ALL_PER_ORG_LIMIT = 10
SEC_ALL_MAX_ITEMS = 60


def load_json(path: Path) -> list:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data.get("items", [])
    return data if isinstance(data, list) else []


def get_field(item: dict, *keys: str) -> str:
    aliases = {
        "org_name":   ["org_name", "org", "agency", "organization", "기관", "기관명"],
        "title":      ["title", "사업명", "공고명", "제목"],
        "url":        ["url", "link", "detail_url", "href"],
        "start_date": ["start_date", "start", "접수시작일", "공고일", "posted_at", "기간", "period"],
        "end_date":   ["end_date", "end", "deadline", "마감일", "접수마감일", "기간", "period"],
    }
    expanded = []
    for k in keys:
        expanded.append(k)
        expanded.extend(aliases.get(k, []))
    for k in expanded:
        v = item.get(k)
        if v:
            return str(v).strip()
    return ""


def _collect_dates_in_order(text: str) -> list[str]:
    """문자열에서 날짜를 YYYY-MM-DD 리스트로 (등장 순). 한글·점 구분 포함."""
    if not text:
        return []
    text = str(text).strip()
    spans: list[tuple[int, str]] = []

    for m in _DATE_YMD.finditer(text):
        spans.append((m.start(), m.group(0)))
    for m in _RE_DOT.finditer(text):
        g = m.group(0)
        y, mo, d = g.split(".")
        spans.append((m.start(), f"{y}-{mo}-{d}"))
    for m in _RE_KO_FULL.finditer(text):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        spans.append((m.start(), f"{y:04d}-{mo:02d}-{d:02d}"))
    for m in _RE_KO_YM.finditer(text):
        y, mo = int(m.group(1)), int(m.group(2))
        spans.append((m.start(), f"{y:04d}-{mo:02d}-28"))

    spans.sort(key=lambda x: x[0])
    return [iso for _, iso in spans]


def _coerce_blob_to_iso(blob: str, which: str) -> str:
    """단일 필드 문자열 → YYYY-MM-DD. 기간이면 which==start면 첫 날, end면 마지막."""
    if not blob:
        return ""
    dates = _collect_dates_in_order(blob)
    if not dates:
        return ""
    return dates[0] if which == "start" else dates[-1]


def _max_iso_date(a: str, b: str) -> str:
    if not a:
        return b
    if not b:
        return a
    return a if a >= b else b


def is_jbexport_item(item: dict) -> bool:
    if not isinstance(item, dict):
        return False
    s = str(item.get("_source") or item.get("source") or "").lower()
    u = str(item.get("url") or item.get("detail_url") or "").lower()
    return ("jbexport" in s) or ("jbexport.or.kr" in u)


def is_jbexport_open(item: dict) -> bool:
    """data/all_sites.json 의 status 문자열만 사용 (보정·제목 참조 없음)."""
    status = str(item.get("status") or "").lower()
    close_keywords = ["마감", "종료", "완료", "선정완료"]
    if any(k in status for k in close_keywords):
        return False
    open_keywords = ["접수", "공고", "진행", "모집", "신청", "사업"]
    if any(k in status for k in open_keywords):
        return True
    return False


def get_date(item: dict, which: str) -> str:
    """
    which: 'start' | 'end'
    period·기간·description 등에서 YYYY-MM-DD·한글·점 형식 추출
    (기간 문자열이면 시작=첫 날짜, 종료=마지막 날짜).
    """
    if which == "start":
        blobs = [
            get_field(item, "start_date"),
            item.get("period"),
            item.get("기간"),
            item.get("description"),
            get_field(item, "end_date"),
        ]
        take = "first"
    elif which == "end":
        blobs = [
            get_field(item, "end_date"),
            item.get("period"),
            item.get("기간"),
            item.get("description"),
            get_field(item, "start_date"),
        ]
        take = "last"
    else:
        return ""

    for blob in blobs:
        if not blob:
            continue
        text = str(blob).strip()
        if not text:
            continue
        dates = _collect_dates_in_order(text)
        if not dates:
            continue
        return dates[0] if take == "first" else dates[-1]
    return ""


def _effective_end_date_str(item: dict) -> str:
    """마감일: BIZINFO 등은 기존 경로. JBEXPORT는 end·기간·본문·title 등에서 추출한 후보 중 최신일(최대값) 사용."""
    if not is_jbexport_item(item):
        s = str(item.get("end_date") or "").strip()
        if s:
            iso = _coerce_blob_to_iso(s, "end")
            if iso:
                return iso
        return get_date(item, "end") or ""

    best = ""
    for blob in (
        item.get("end_date"),
        item.get("period"),
        item.get("기간"),
        item.get("description"),
        item.get("raw_period"),
        item.get("raw_period_preview"),
        item.get("title"),
    ):
        if blob is None:
            continue
        t = str(blob).strip()
        if not t:
            continue
        iso = _coerce_blob_to_iso(t, "end")
        if iso:
            best = _max_iso_date(best, iso)
    gd = get_date(item, "end")
    if gd:
        best = _max_iso_date(best, gd)
    return best


def _effective_start_date_str(item: dict) -> str:
    """start_date 우선(한글·기간 파싱), 없으면 get_date(start)."""
    s = str(item.get("start_date") or "").strip()
    if s:
        iso = _coerce_blob_to_iso(s, "start")
        if iso:
            return iso
    return get_date(item, "start") or ""


def is_active(item: dict) -> bool:
    if is_jbexport_item(item):
        if is_jbexport_open(item):
            return True
        return False

    end = _effective_end_date_str(item)
    if not end:
        return False
    try:
        end_dt = datetime.strptime(end, "%Y-%m-%d").date()
        return end_dt >= today
    except Exception:
        return False


def is_new(item: dict) -> bool:
    start = _effective_start_date_str(item)
    if not start:
        return False
    try:
        start_dt = datetime.strptime(start, "%Y-%m-%d").date()
        return 0 <= (today - start_dt).days <= 7
    except Exception:
        return False


def is_ending_soon(item: dict) -> bool:
    end = _effective_end_date_str(item)
    if not end:
        return False
    try:
        end_dt = datetime.strptime(end, "%Y-%m-%d").date()
        return 0 <= (end_dt - today).days <= 7
    except Exception:
        return False


def build_active_section(items: list, cap: int = 60) -> str:
    lines: list[str] = []

    for x in items[:cap]:
        title = x.get("title", "")
        url = x.get("url", "")
        src = x.get("_source", "")

        lines.append(f"[{src}] {title}")
        lines.append(f"링크: {url}")
        lines.append("")

    return "\n".join(lines)


def get_item_key(x: dict) -> str:
    """diff_new.get_item_key 과 동일: url→detail_url→spSeq→id→title|organization(org_name)."""
    if not isinstance(x, dict):
        return ""
    return (
        str(x.get("url") or "").strip()
        or str(x.get("detail_url") or "").strip()
        or str(x.get("spSeq") or "").strip()
        or str(x.get("id") or "").strip()
        or f"{str(x.get('title', '')).strip()}|{str(x.get('organization') or x.get('org_name') or '').strip()}"
    )


def _item_dedupe_key(item: dict) -> str:
    return get_item_key(item)


def _dedupe_merge_pref_file(file_list: list, derived_list: list) -> list:
    """파일 목록을 먼저 넣고, 이어서 파생 목록에서 URL·제목 기준 미등록만 추가."""
    seen: set[str] = set()
    out: list[dict] = []
    for lst in (file_list, derived_list):
        for x in lst:
            if not isinstance(x, dict):
                continue
            k = _item_dedupe_key(x)
            if k in seen:
                continue
            seen.add(k)
            out.append(x)
    return out


def group_by_org(items: list) -> dict:
    g = defaultdict(list)
    for x in items:
        org = get_field(x, "org_name", "agency", "organization") or "기타"
        g[org].append(x)
    return g


def fmt_item(item: dict, show_dday: bool = False) -> str:
    title   = get_field(item, "title") or "(제목없음)"
    start   = get_field(item, "start_date")
    end     = get_field(item, "end_date")
    url     = get_field(item, "url", "detail_url")
    period  = f"{start} ~ {end}" if start and end else (end or start or "-")
    dday    = f" (D-{item.get('d_day', '')})" if show_dday and item.get("d_day", "") != "" else ""

    lines = [f"  - {title}"]
    lines.append(f"    기간: {period}{dday}")
    if url:
        lines.append(f"    링크: {url}")
    return "\n".join(lines)


def build_section(title: str, icon: str, items: list,
                  show_dday: bool = False, limit: int = 30,
                  max_total_items: int | None = None) -> str:
    if not items:
        return f"{icon} {title}\n  해당 공고 없음\n"

    # 중복 제거 (url → detail_url → id → title|organization)
    seen = set()
    deduped = []
    for x in items:
        key = _item_dedupe_key(x)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(x)

    grouped = group_by_org(deduped)
    lines   = [f"{icon} {title}"]

    if max_total_items is not None:
        # 기관당 limit·전체 max를 동시에 만족하려면 기관별로 한 번만 자르면 안 됨 → 라운드로빈
        orgs = list(grouped.keys())
        idx = {o: 0 for o in orgs}
        n_org = {o: 0 for o in orgs}
        picked: list[tuple[str, dict]] = []
        while len(picked) < max_total_items:
            progressed = False
            for org in orgs:
                if len(picked) >= max_total_items:
                    break
                if n_org[org] >= limit:
                    continue
                i = idx[org]
                org_list = grouped[org]
                if i >= len(org_list):
                    continue
                picked.append((org, org_list[i]))
                idx[org] = i + 1
                n_org[org] += 1
                progressed = True
            if not progressed:
                break
        shown = len(picked)
        cur_org = None
        for org, item in picked:
            if org != cur_org:
                lines.append(f"\n  [{org}]")
                cur_org = org
            lines.append(fmt_item(item, show_dday=show_dday))
    else:
        shown = 0
        for org, org_items in grouped.items():
            lines.append(f"\n  [{org}]")
            for item in org_items[:limit]:
                lines.append(fmt_item(item, show_dday=show_dday))
                shown += 1

    if max_total_items is not None and shown < len(deduped):
        lines.append(f"\n  … 외 {len(deduped) - shown}건 (전체 목록은 사이트에서 확인)")

    return "\n".join(lines)


def normalize_status(text: str) -> str:
    if not text:
        return ""
    return str(text).strip().replace(" ", "")


ACTIVE_KEYWORDS = [
    "접수중",
    "공고중",
    "접수",
    "진행중",
    "신청가능",
    "모집중",
    "사업공고",
    "상시",
    "공고",
]

CLOSED_KEYWORDS = [
    "마감",
    "종료",
    "완료",
    "접수마감",
    "선정완료",
]


def is_active_by_status(item: dict) -> bool:
    status = normalize_status(
        item.get("status")
        or item.get("state")
        or item.get("progress_status")
        or item.get("condition")
        or ""
    )

    if not status:
        return True

    if any(k in status for k in CLOSED_KEYWORDS):
        return False

    if any(k in status for k in ACTIVE_KEYWORDS):
        return True

    # 기본은 포함
    return True


def is_bizinfo_item(item: dict) -> bool:
    src = str(
        item.get("_source")
        or item.get("source")
        or item.get("site")
        or ""
    ).lower()
    return "bizinfo" in src


def passes_bizinfo_relevance(item: dict) -> bool:
    # JBEXPORT 및 기타는 무조건 통과
    if not is_bizinfo_item(item):
        return True

    text = " ".join([
        str(item.get("title", "")),
        str(item.get("description", "")),
        str(item.get("organization", "")),
        str(item.get("org_name", "")),
    ]).lower()

    # BIZINFO: 수출·무역·해외·전시·바우처·인증·물류·시장개척 계열만 (전시회/박람회는 '전시' 미포함 시 보조)
    include_keywords = [
        "수출",
        "무역",
        "해외",
        "전시",
        "바우처",
        "인증",
        "물류",
        "시장개척",
        "박람회",
    ]

    exclude_keywords = [
        "창업교육", "교육", "강의", "음식점", "외식", "카페",
        "농업", "귀농", "복지", "청년복지", "문화", "예술", "공연",
        "관광", "해설사", "사회적기업(일반지원)", "평생교육",
    ]

    if any(k in text for k in exclude_keywords):
        return False

    if any(k in text for k in include_keywords):
        return True

    return False


def main():
    all_items = load_json(ALL_FILE)
    new_items_raw = load_json(NEW_FILE)

    jb_all = [x for x in all_items if isinstance(x, dict) and is_jbexport_item(x)]
    jb_open = [x for x in jb_all if is_jbexport_open(x)]
    print(f"[mail] jbexport_total: {len(jb_all)}")
    print(f"[mail] jbexport_open_status: {len(jb_open)}")

    active_items = [
        x for x in all_items if is_active(x) and passes_bizinfo_relevance(x)
    ]
    ending_items = [
        x for x in all_items if is_ending_soon(x) and passes_bizinfo_relevance(x)
    ]
    new_items = [
        x for x in new_items_raw if is_new(x) and passes_bizinfo_relevance(x)
    ]

    print(f"[mail] all_items: {len(all_items)}")
    print(f"[mail] new_items_raw: {len(new_items_raw)}")
    print(f"[mail] active: {len(active_items)}")
    jb_in_mail = sum(1 for x in active_items if is_jbexport_item(x))
    print(f"[mail] jbexport_in_active_mail: {jb_in_mail}")
    print(f"[mail] new: {len(new_items)}")
    print(f"[mail] ending soon: {len(ending_items)}")

    body = ""

    body += "전북지원사업 메일자동알림서비스입니다.\n\n"

    body += "🔥 신규 공고\n"
    if new_items:
        body += build_active_section(new_items)
    else:
        body += "해당 공고 없음\n"

    body += "\n⚠ 마감 임박\n"
    if ending_items:
        body += build_active_section(ending_items)
    else:
        body += "해당 공고 없음\n"

    body += "\n📌 전체 접수중\n"
    if active_items:
        body += build_active_section(active_items, cap=SEC_ALL_MAX_ITEMS)
    else:
        body += "해당 공고 없음\n"

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(body, encoding="utf-8")

    print(f"[make_mail] 저장: {OUT_FILE}")


if __name__ == "__main__":
    main()
