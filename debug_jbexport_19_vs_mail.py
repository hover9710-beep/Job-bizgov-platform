# -*- coding: utf-8 -*-
"""
JBEXPORT 집합 vs make_mail active 비교 (data/all_sites.json).
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from datetime import datetime

from pipeline import make_mail as mm

ALL_FILE = Path("data/all_sites.json")

OPEN_KEYWORDS = ("접수중", "공고중", "진행", "모집중", "신청가능")
CLOSED_SUBSTR = ("마감", "접수마감", "종료", "완료", "선정완료")


def load_json(path: Path) -> list:
    if not path.exists():
        return []
    import json

    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data.get("items", [])
    return data if isinstance(data, list) else []


def is_jbexport(x: dict) -> bool:
    s = str(x.get("_source") or x.get("source") or x.get("site") or "").lower()
    u = str(x.get("url") or x.get("detail_url") or "").lower()
    return ("jbexport" in s) or ("jbexport.or.kr" in u)


def status_open_candidate(st: str) -> bool:
    st = str(st or "").strip()
    if not st:
        return False
    for c in CLOSED_SUBSTR:
        if c in st:
            return False
    for k in OPEN_KEYWORDS:
        if k in st:
            return True
    return False


def url_key(x: dict) -> str:
    return str(x.get("url") or x.get("detail_url") or "").strip()


def raw_period_blob(x: dict) -> str:
    parts = [
        x.get("period"),
        x.get("기간"),
        x.get("description"),
        x.get("raw_period"),
        x.get("raw_period_preview"),
    ]
    return " | ".join(str(p) for p in parts if p)


def drop_reason_missing(x: dict) -> str:
    st = str(x.get("status") or "")
    if any(c in st for c in CLOSED_SUBSTR):
        return "status_closed"
    eff = mm._effective_end_date_str(x)
    if not eff:
        return "no_end_date"
    try:
        ed = datetime.strptime(eff[:10], "%Y-%m-%d").date()
    except ValueError:
        return "unparsable_end"
    if ed < mm.today:
        return "end_before_today"
    if not (mm.is_active(x) and mm.passes_bizinfo_relevance(x)):
        return "filtered_elsewhere"
    return "unknown"


def main():
    items = load_json(ALL_FILE)
    jb_all = [x for x in items if isinstance(x, dict) and is_jbexport(x)]

    jb_status_open_19 = [x for x in jb_all if status_open_candidate(x.get("status"))]
    jb_mail_active = [
        x
        for x in jb_all
        if mm.is_active(x) and mm.passes_bizinfo_relevance(x)
    ]

    mail_urls = {url_key(x) for x in jb_mail_active}
    missing_from_mail = [x for x in jb_status_open_19 if url_key(x) not in mail_urls]

    print("[JBEXPORT COUNT]")
    print("- jb_all:", len(jb_all))
    print("- jb_status_open_19:", len(jb_status_open_19))
    print("- jb_mail_active:", len(jb_mail_active))
    print("- missing_from_mail:", len(missing_from_mail))
    print()

    if len(jb_mail_active) > len(jb_status_open_19):
        print(
            "[NOTE] jb_mail_active > jb_status_open_19 이면, status 키워드에 없어도 "
            "(예: 확인 필요) 제목·기간에서 마감 후보를 잡아 is_active 통과한 JBEXPORT가 있음."
        )
        print()

    print("[JBEXPORT MISSING DETAILS]")
    for x in missing_from_mail:
        eff_s = mm._effective_start_date_str(x)
        eff_e = mm._effective_end_date_str(x)
        dr = drop_reason_missing(x)
        print("- title:", str(x.get("title") or "")[:120])
        print("  status:", str(x.get("status") or ""))
        print("  org:", str(x.get("org_name") or x.get("organization") or ""))
        print("  url:", url_key(x)[:160])
        print("  start_date:", str(x.get("start_date") or ""))
        print("  end_date:", str(x.get("end_date") or ""))
        print("  effective_start:", eff_s)
        print("  effective_end:", eff_e)
        print("  raw period/기간/desc:", raw_period_blob(x)[:200])
        print("  drop_reason:", dr)
        print()


if __name__ == "__main__":
    main()
