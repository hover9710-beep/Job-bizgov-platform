# -*- coding: utf-8 -*-
"""
JBEXPORT: status(진행) vs 메일 반영(is_active) 검증.

- make_mail.is_active + passes_bizinfo_relevance 와 동일.
- open 후보: status == '진행' (jbexport JSON 관례).

주의 (19건 기대와 숫자가 다를 때):
- 메일 건수 상한은 **저장된 JSON**의 날짜·상태에 따른다.
- 현재 워크스페이스 기준 data/all_jb.json·data/all_sites.json 의
  "status":"진행" 개수는 **14건**이며, is_active 통과 JBEXPORT도 **14건**이면
  메일 14건 = **누락 없음(데이터 일치)**.
- 사이트에서 접수중이 19건으로 보이는데 메일이 14건이면, 원인은 코드가 아니라
  **크롤 스냅샷이 오래됐거나**, **merge 전 all_jb 미갱신**, 또는 **status/마감일이
  JSON에 아직 반영되지 않은 경우**가 많다. JBEXPORT 크롤·merge 후 재실행해 비교한다.
"""
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pipeline import make_mail as mm

ALL_FILE = Path("data/all_sites.json")
JB_FILE = Path("data/all_jb.json")


def load_json(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data.get("items", [])
    return data if isinstance(data, list) else []


def src_of(x):
    return str(
        x.get("_source") or x.get("source") or x.get("site") or ""
    ).lower()


def is_jbexport(x):
    s = src_of(x)
    u = str(x.get("url") or x.get("detail_url") or "")
    return ("jbexport" in s) or ("jbexport.or.kr" in u)


def get_status(x):
    return str(
        x.get("status")
        or x.get("state")
        or x.get("progress_status")
        or x.get("condition")
        or ""
    ).strip()


def get_title(x):
    return str(x.get("title") or "")


def get_url(x):
    return str(x.get("url") or x.get("detail_url") or "")


def is_open_status_jbexport(x):
    """jbexport 원본은 '진행' / '마감' 위주 (접수중·공고중 거의 없음)."""
    st = get_status(x)
    return st == "진행"


def mail_eligible_jbexport(x):
    """make_mail main() 과 동일."""
    return mm.is_active(x) and mm.passes_bizinfo_relevance(x)


def why_not_active(x):
    end_raw = str(x.get("end_date") or "").strip()
    eff = mm._effective_end_date_str(x)
    if not eff:
        return "no_end_date(effective empty)"
    try:
        from datetime import datetime

        end_dt = datetime.strptime(eff[:10], "%Y-%m-%d").date()
        today = mm.today
        if end_dt < today:
            return f"ended(end={eff} < today)"
    except ValueError:
        return f"unparseable_end(eff={eff!r}, raw={end_raw!r})"
    return "unknown"


def main():
    items = load_json(ALL_FILE)
    jb = [x for x in items if isinstance(x, dict) and is_jbexport(x)]

    open_jb = [x for x in jb if is_open_status_jbexport(x)]
    mail_jb = [x for x in jb if mail_eligible_jbexport(x)]

    jb_raw_count = None
    jb_raw_jin = None
    if JB_FILE.exists():
        jb_raw = load_json(JB_FILE)
        jb_raw_list = [x for x in jb_raw if isinstance(x, dict)]
        jb_raw_count = len(jb_raw_list)
        jb_raw_jin = sum(
            1 for x in jb_raw_list if str(x.get("status") or "").strip() == "진행"
        )

    mail_urls = {get_url(x) for x in mail_jb}
    missing = [x for x in open_jb if get_url(x) not in mail_urls]

    print("=== JBEXPORT vs 메일 (make_mail 기준) ===")
    print("JBEXPORT total (all_sites):", len(jb))
    if jb_raw_count is not None:
        print(f"JBEXPORT total (all_jb.json): {jb_raw_count}")
        print(f'all_jb.json status=="진행"   : {jb_raw_jin}')
    print("open (status==진행, merged):", len(open_jb))
    print("mail (is_active+pass)      :", len(mail_jb))
    print("missing (진행인데 메일 없음):", len(missing))
    if len(open_jb) == len(mail_jb) and len(missing) == 0:
        print()
        print("[검증] 진행 건수 == 메일 반영 건수 → 저장 JSON·날짜 기준 누락 없음.")
    print()

    by_status = {}
    for x in jb:
        st = get_status(x) or "(빈값)"
        by_status[st] = by_status.get(st, 0) + 1
    print("status 분포 (상위 8개):", sorted(by_status.items(), key=lambda t: -t[1])[:8])
    print()

    for i, x in enumerate(missing, 1):
        print("=" * 80)
        print(i, get_title(x))
        print("status   :", get_status(x))
        print("end_date :", repr(str(x.get("end_date") or "")))
        print("effective:", repr(mm._effective_end_date_str(x)))
        print("reason   :", why_not_active(x))
        print("url      :", get_url(x))


if __name__ == "__main__":
    main()
