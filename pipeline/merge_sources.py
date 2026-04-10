# -*- coding: utf-8 -*-
"""
pipeline/merge_sources.py
JBEXPORT + Bizinfo 데이터 병합 → data/all_sites.json
사용: py pipeline/merge_sources.py
"""

import json
import sys
from pathlib import Path
from datetime import datetime

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pipeline.bizinfo_dates import first_raw_period_preview, parse_bizinfo_dates

TODAY    = datetime.now().strftime("%Y-%m-%d")

# ── 소스 파일 경로 ──────────────────────
JB_FILE      = Path("data/all_jb.json")
BIZINFO_FILE = Path("data/bizinfo/json/bizinfo_all.json")  # 기본 후보
OUT_FILE     = Path("data/all_sites.json")


def load_json(path: Path) -> list:
    if not path.exists():
        print(f"[merge] 파일 없음: {path}")
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data.get("items", [])
    return data if isinstance(data, list) else []


def find_bizinfo_file() -> Path | None:
    """bizinfo JSON 파일 자동 탐색 (bizinfo_all.json 우선, sample·임시 파일 제외)."""
    candidates = [
        Path("data/bizinfo/json/bizinfo_all.json"),
        Path("data/all_jb/bizinfo_all.json"),
        Path("data/bizinfo_all.json"),
        Path("data/all_jb.json").parent / "bizinfo_all.json",
    ]
    seen = {str(c) for c in candidates}
    for f in sorted(Path("data").rglob("bizinfo*.json")):
        fs = str(f)
        if fs in seen:
            continue
        low = f.name.lower()
        if "sample" in low or "temp" in low or "test" in low:
            continue
        candidates.append(f)
        seen.add(fs)

    for c in candidates:
        if c.exists():
            print(f"[merge] bizinfo 파일 발견: {c}")
            return c

    print("[merge] bizinfo 파일 없음 → JBEXPORT만 사용")
    return None


def normalize(item: dict, source: str) -> dict:
    obj = dict(item)
    obj["_source"] = source
    return obj


def enrich_bizinfo_dates(item: dict, index: int) -> dict:
    """Fill start_date / end_date for BIZINFO rows (canonical YYYY-MM-DD)."""
    obj = dict(item)
    dates = parse_bizinfo_dates(obj)
    obj["start_date"] = dates["start_date"]
    obj["end_date"] = dates["end_date"]
    if index < 10:
        print(
            "[bizinfo-date]",
            {
                "title": (obj.get("title") or "")[:40],
                "detail_url": (obj.get("url") or "")[:100],
                "raw_period": first_raw_period_preview(obj),
                "start_date": obj.get("start_date", ""),
                "end_date": obj.get("end_date", ""),
            },
            flush=True,
        )
    return obj


def _bizinfo_stats(rows: list) -> dict:
    biz = [x for x in rows if isinstance(x, dict) and x.get("_source") == "BIZINFO"]
    n = len(biz)
    n_sd = sum(1 for x in biz if str(x.get("start_date") or "").strip())
    n_ed = sum(1 for x in biz if str(x.get("end_date") or "").strip())
    n_both = sum(
        1
        for x in biz
        if str(x.get("start_date") or "").strip() and str(x.get("end_date") or "").strip()
    )
    return {
        "total": n,
        "with_start": n_sd,
        "with_end": n_ed,
        "with_both": n_both,
        "sample": biz[:10],
    }


def main():
    # JBEXPORT 로드
    jb_items = load_json(JB_FILE)
    print(f"[merge] JBEXPORT: {len(jb_items)}건")

    # Bizinfo 로드
    bizinfo_path = find_bizinfo_file()
    bizinfo_items = []
    if bizinfo_path:
        bizinfo_items = load_json(bizinfo_path)
        print(f"[merge] Bizinfo: {len(bizinfo_items)}건")
    else:
        print("[merge] Bizinfo: 0건")

    # 소스 태그
    jb_items = [normalize(x, "JBEXPORT") for x in jb_items]
    bizinfo_items = [
        enrich_bizinfo_dates(normalize(x, "BIZINFO"), i)
        for i, x in enumerate(bizinfo_items)
    ]

    # 병합
    all_items = jb_items + bizinfo_items

    # 중복 제거 (url 기준)
    seen  = set()
    dedup = []
    for x in all_items:
        key = (
            x.get("url")
            or x.get("detail_url")
            or x.get("id")
            or str(x.get("title", ""))
        )
        if key and key not in seen:
            seen.add(key)
            dedup.append(x)

    print(f"[merge] 병합 후 총: {len(dedup)}건 (중복 제거 전: {len(all_items)}건)")

    # 저장
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(dedup, f, ensure_ascii=False, indent=2)

    print(f"[merge] 저장: {OUT_FILE}")

    st = _bizinfo_stats(dedup)
    print(
        "[merge] BIZINFO date summary: "
        f"total={st['total']} start_date nonempty={st['with_start']} "
        f"end_date nonempty={st['with_end']} both={st['with_both']}"
    )
    print("[merge] BIZINFO first 10 (title / detail_url / start_date / end_date / raw_period):")
    for i, row in enumerate(st["sample"], 1):
        rp = (
            str(row.get("raw_period") or "").strip()
            or str(row.get("period") or "").strip()
            or first_raw_period_preview(row)
        )
        print(
            f"  {i}. title={str(row.get('title',''))[:55]!r}\n"
            f"      detail_url={str(row.get('url',''))[:95]!r}\n"
            f"      start_date={row.get('start_date')!r} end_date={row.get('end_date')!r}\n"
            f"      raw_period={rp[:120]!r}",
            flush=True,
        )

    return dedup


if __name__ == "__main__":
    main()
