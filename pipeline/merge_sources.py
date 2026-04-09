# -*- coding: utf-8 -*-
"""
pipeline/merge_sources.py
JBEXPORT + Bizinfo 데이터 병합 → data/all_sites.json
사용: py pipeline/merge_sources.py
"""

import json
from pathlib import Path
from datetime import datetime

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
    """bizinfo JSON 파일 자동 탐색"""
    candidates = [
        Path("data/bizinfo/json/bizinfo_all.json"),
        Path("data/all_jb/bizinfo_all.json"),
        Path("data/bizinfo_all.json"),
        Path("data/all_jb.json").parent / "bizinfo_all.json",
    ]

    for f in Path("data").rglob("bizinfo*.json"):
        candidates.insert(0, f)

    seen = set()
    uniq = []
    for c in candidates:
        key = str(c)
        if key not in seen:
            seen.add(key)
            uniq.append(c)

    for c in uniq:
        if c.exists():
            print(f"[merge] bizinfo 파일 발견: {c}")
            return c

    print("[merge] bizinfo 파일 없음 → JBEXPORT만 사용")
    return None


def normalize(item: dict, source: str) -> dict:
    obj = dict(item)
    obj["_source"] = source
    return obj


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
    jb_items      = [normalize(x, "JBEXPORT") for x in jb_items]
    bizinfo_items = [normalize(x, "BIZINFO") for x in bizinfo_items]

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
    return dedup


if __name__ == "__main__":
    main()
