# -*- coding: utf-8 -*-
"""
pipeline/make_mail.py
메일 본문 생성 — 날짜 기준: 진행 중 / 신규(7일) / 곧 마감(7일)
"""

import json
import re
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path

_DATE_YMD = re.compile(r"\d{4}-\d{2}-\d{2}")

today = datetime.today().date()

ALL_FILE = Path("data/all_sites.json")
NEW_FILE = Path("data/new.json")
DB_FILE = Path("db/biz.db")
OUT_FILE = Path("data/mail/mail_body.txt")

# 전체 접수중 섹션 가독성 (기관당 / 전체 상한)
# 기관당이 너무 낮으면 기관 수·소형 기관 한도 때문에 전체 상한(60)에 못 미침 (예: 8×9 - 소형 = 53)
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


def load_active_bizinfo_from_db(db_path: Path) -> list:
    """
    bizinfo는 all_sites.json이 아닌 DB에서 직접 조회:
      source='bizinfo' AND end_date >= date('now')
    """
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT
                title,
                organization,
                source,
                start_date,
                end_date,
                status,
                url,
                description
            FROM biz_projects
            WHERE source='bizinfo'
              AND end_date IS NOT NULL
              AND TRIM(end_date) != ''
              AND end_date >= date('now')
            """
        ).fetchall()
    finally:
        conn.close()

    out = []
    for r in rows:
        d = dict(r)
        out.append(
            {
                "title": d.get("title") or "",
                "organization": d.get("organization") or "",
                "source": d.get("source") or "bizinfo",
                "_source": d.get("source") or "bizinfo",
                "start_date": d.get("start_date") or "",
                "end_date": d.get("end_date") or "",
                "status": d.get("status") or "",
                "url": d.get("url") or "",
                "description": d.get("description") or "",
            }
        )
    return out


def get_field(item: dict, *keys: str) -> str:
    aliases = {
        "org_name":   ["org_name", "org", "agency", "organization", "기관", "기관명"],
        "title":      ["title", "사업명", "공고명", "제목"],
        "url":        ["url", "link", "detail_url", "href"],
        "start_date": ["start_date", "start", "receipt_start", "접수시작일", "공고일", "posted_at", "기간", "period"],
        "end_date":   ["end_date", "end", "receipt_end", "deadline", "마감일", "접수마감일", "기간", "period"],
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


def get_date(item: dict, which: str) -> str:
    """
    which: 'start' | 'end'
    우선 해당 키(start_date / end_date), 없거나 날짜가 없으면 period·기간·description 등에서
    YYYY-MM-DD 패턴만 추출 (기간 문자열이면 시작=첫 날짜, 종료=마지막 날짜).
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
        dates = _DATE_YMD.findall(text)
        if not dates:
            continue
        return dates[0] if take == "first" else dates[-1]
    return ""


def is_active(item: dict) -> bool:
    end = item.get("end_date")
    if not end:
        return False
    try:
        end_dt = datetime.strptime(end, "%Y-%m-%d").date()
        return end_dt >= today
    except Exception:
        return False


def is_new(item: dict) -> bool:
    start = item.get("start_date")
    if not start:
        return False
    try:
        start_dt = datetime.strptime(start, "%Y-%m-%d").date()
        return 0 <= (today - start_dt).days <= 7
    except Exception:
        return False


def is_ending_soon(item: dict) -> bool:
    end = item.get("end_date")
    if not end:
        return False
    try:
        end_dt = datetime.strptime(end, "%Y-%m-%d").date()
        return 0 <= (end_dt - today).days <= 7
    except Exception:
        return False


def build_active_section(items: list, cap: int = 60) -> str:
    lines: list[str] = []
    for i, x in enumerate(items[:cap], start=1):
        if not isinstance(x, dict):
            continue
        title = get_field(x, "title") or "(제목 없음)"
        org = get_field(x, "organization", "org_name", "agency") or "-"
        url = get_field(x, "url", "detail_url") or "-"
        src = (get_field(x, "source", "_source") or "").upper()
        src = src if src else "UNKNOWN"
        start = get_field(x, "start_date")
        end = get_field(x, "end_date")
        period = f"{start} ~ {end}" if start and end else (end or start or "-")

        lines.append(f"{i}. [{src}] {title}")
        lines.append(f"   기관: {org}")
        lines.append(f"   기간: {period}")
        lines.append(f"   링크: {url}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _item_dedupe_key(item: dict) -> str:
    u = get_field(item, "url", "detail_url", "id")
    if u:
        return u
    return f"{get_field(item, 'title')}|{get_field(item, 'org_name', 'organization')}"


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

    # 중복 제거 (url 기준)
    seen = set()
    deduped = []
    for x in items:
        key = get_field(x, "url", "detail_url", "id")
        if key not in seen:
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


INCLUDE_BIZINFO_KEYWORDS = [
    "수출", "해외", "글로벌", "무역",
    "바우처", "수출바우처",
    "전시회", "박람회",
    "해외진출", "시장개척",
    "판로", "유통", "마케팅",
    "브랜드", "디자인",
    "인증", "규격", "CE", "FDA",
    "물류", "배송",
]

EXCLUDE_BIZINFO_KEYWORDS = [
    "창업교육", "교육", "강의",
    "음식점", "외식", "카페",
    "농업", "농촌", "귀농",
    "복지", "청년복지",
    "문화", "예술", "공연",
    "관광", "해설사",
    "사회적기업(일반지원)",
    "평생교육",
]


def is_relevant_bizinfo(item: dict) -> bool:
    title = str(item.get("title", ""))
    desc = str(item.get("description", ""))
    org = str(item.get("organization", ""))
    text = f"{title} {desc} {org}"

    # 강한 제외 먼저
    if any(k in text for k in EXCLUDE_BIZINFO_KEYWORDS):
        return False

    # 포함 조건
    if any(k in text for k in INCLUDE_BIZINFO_KEYWORDS):
        return True

    # 기본 차단 (이게 핵심)
    return False


def main():
    all_items_raw = load_json(ALL_FILE)
    new_items_raw = load_json(NEW_FILE)
    # JSON 기반에서는 bizinfo 제외(jbexport/기타 유지)
    json_non_bizinfo = [
        x for x in all_items_raw
        if isinstance(x, dict) and str(x.get("source") or "").strip().lower() != "bizinfo"
    ]
    # bizinfo active는 DB에서 직접 조회
    db_bizinfo_active = load_active_bizinfo_from_db(DB_FILE)
    # 최종 all_items = JSON 기반(비-bizinfo) + DB 기반 bizinfo
    all_items = json_non_bizinfo + db_bizinfo_active

    active_items = [x for x in all_items if is_active(x)]
    ending_items = [x for x in all_items if is_ending_soon(x)]
    new_items = [x for x in new_items_raw if is_new(x)]

    jb_active = sum(
        1 for x in active_items
        if isinstance(x, dict) and str(x.get("source") or "").strip().lower() == "jbexport"
    )
    biz_active = sum(
        1 for x in active_items
        if isinstance(x, dict) and str(x.get("source") or "").strip().lower() == "bizinfo"
    )

    print(f"[mail] all_items(raw_json): {len(all_items_raw)}")
    print(f"[mail] all_items(merged): {len(all_items)}")
    print(f"[mail] new_items_raw: {len(new_items_raw)}")
    print(f"[mail] active: {len(active_items)}")
    print(f"[mail] jbexport_active: {jb_active}")
    print(f"[mail] bizinfo_active(db): {biz_active}")
    print(f"[mail] new: {len(new_items)}")
    print(f"[mail] ending soon: {len(ending_items)}")

    body = ""
    sep = "-" * 40
    body += "전북지원사업 메일자동알림서비스입니다.\n\n"

    body += f"🔥 신규 공고 ({len(new_items)}건)\n"
    body += build_active_section(new_items) if new_items else "해당 공고 없음\n"
    body += f"\n{sep}\n\n"

    body += f"⚠ 마감 임박 공고 ({len(ending_items)}건)\n"
    body += build_active_section(ending_items) if ending_items else "해당 공고 없음\n"
    body += f"\n{sep}\n\n"

    active_limited = active_items[:SEC_ALL_MAX_ITEMS]
    body += f"📌 전체 접수중 공고 ({len(active_items)}건)\n"
    body += build_active_section(active_limited, cap=SEC_ALL_MAX_ITEMS) if active_items else "해당 공고 없음\n"

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(body, encoding="utf-8")

    print(f"[make_mail] 저장: {OUT_FILE}")


if __name__ == "__main__":
    main()
