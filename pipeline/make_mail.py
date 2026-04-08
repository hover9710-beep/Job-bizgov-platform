# -*- coding: utf-8 -*-
"""
pipeline/make_mail.py
메일 본문 생성 — 신규 / 마감임박 / 전체 접수중 (기관별 그룹)
"""

import json
from collections import defaultdict
from pathlib import Path

ALL_FILE      = Path("data/all_jb.json")
NEW_FILE      = Path("data/jbexport_new.json")
DEADLINE_FILE = Path("data/processed/deadline.json")
OUT_FILE      = Path("data/mail/mail_body.txt")


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
        "start_date": ["start_date", "start", "접수시작일", "공고일", "posted_at"],
        "end_date":   ["end_date", "end", "deadline", "마감일", "접수마감일"],
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
                  show_dday: bool = False, limit: int = 30) -> str:
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

    for org, org_items in grouped.items():
        lines.append(f"\n  [{org}]")
        for item in org_items[:limit]:
            lines.append(fmt_item(item, show_dday=show_dday))

    return "\n".join(lines)


def main():
    # ── 디버그: 소스 파일 확인 ──────────
    print(f"[make_mail] ALL_FILE: {ALL_FILE} exists={ALL_FILE.exists()}")
    print(f"[make_mail] NEW_FILE: {NEW_FILE} exists={NEW_FILE.exists()}")
    print(f"[make_mail] DEADLINE_FILE: {DEADLINE_FILE} exists={DEADLINE_FILE.exists()}")

    all_items = load_json(ALL_FILE)
    new_items = load_json(NEW_FILE)
    deadline_items = load_json(DEADLINE_FILE)

    if not all_items:
        raw_dir = Path("data/raw")
        candidates = sorted(
            raw_dir.glob("*.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        for f in candidates:
            try:
                with open(f, encoding="utf-8") as fh:
                    fallback = json.load(fh)
                if isinstance(fallback, list) and fallback:
                    all_items = fallback
                    print(f"[make_mail] fallback 파일 사용: {f}")
                    break
                elif isinstance(fallback, dict):
                    tmp = fallback.get("items", [])
                    if tmp:
                        all_items = tmp
                        print(f"[make_mail] fallback 파일 사용: {f}")
                        break
            except Exception:
                continue

    if all_items:
        print(f"[make_mail] all_items: {len(all_items)}건, keys={list(all_items[0].keys())[:6]}")
    print(f"[make_mail] jbexport_new.json: {len(new_items)}건")
    print(f"[make_mail] deadline.json: {len(deadline_items)}건")

    # ── 분류: 파일 우선 사용 ─────────────────
    active_items = [
        x for x in all_items
        if x.get("status") in ["접수중", "공고중", "접수", "진행중"]
    ]

    # 신규는 jbexport_new.json 우선
    final_new_items = new_items if new_items else []

    # 마감임박은 deadline.json 우선
    final_deadline_items = deadline_items if deadline_items else []

    print(f"[make_mail] 신규: {len(final_new_items)}건")
    print(f"[make_mail] 마감임박: {len(final_deadline_items)}건")
    print(f"[make_mail] 접수중: {len(active_items)}건")

    deadline_sorted = sorted(
        final_deadline_items,
        key=lambda x: get_field(x, "end_date") or "9999-12-31",
    )

    # 섹션 생성
    sec_new      = build_section("신규 공고 (최근 7일)",  "🔥", final_new_items)
    sec_deadline = build_section("마감임박 공고 (D-7)",   "⚠",  deadline_sorted, show_dday=True)
    sec_all      = build_section("전체 접수중 공고",       "📌", active_items, limit=20)

    body = f"""전북지원사업 메일자동알림서비스입니다.

────────────────────────────
{sec_new}

────────────────────────────
{sec_deadline}

────────────────────────────
{sec_all}

────────────────────────────
※ 본 메일은 지원사업 공고를 자동 수집하여 발송됩니다.
※ 자세한 신청 조건은 반드시 각 기관의 공고문 원문을 확인해 주세요.
"""

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(body, encoding="utf-8")

    print(f"[make_mail] 저장: {OUT_FILE}")


if __name__ == "__main__":
    main()
