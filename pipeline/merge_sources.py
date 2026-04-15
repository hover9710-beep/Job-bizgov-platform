# -*- coding: utf-8 -*-
"""
data/raw/*.json 자동 병합 → data/merged/all_sites.json + history 스냅샷.

- 재크롤링 없음 (connector 출력 JSON만 읽음)
- raw 폴더에 json 추가 시 자동 포함 (사이트명 하드코딩 없음)
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pipeline.bizinfo_dates import parse_bizinfo_biz_dates, parse_bizinfo_receipt_dates
from pipeline.project_quality import canonical_notice_source
from pipeline.data_paths import (
    ALL_SITES_JSON,
    HISTORY_DIR,
    MERGED_DIR,
    RAW_DIR,
    ensure_pipeline_dirs,
)

TODAY_STR = datetime.now().strftime("%Y-%m-%d")


def discover_raw_files(raw_dir: Path) -> list[Path]:
    """data/raw 내 *.json 전부 (정렬)."""
    if not raw_dir.is_dir():
        return []
    return sorted(raw_dir.glob("*.json"), key=lambda p: p.name.lower())


def load_any_json(path: Path) -> list:
    """리스트 또는 {\"items\": [...]} 형식."""
    if not path.exists():
        print(f"[merge] 파일 없음: {path}")
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, TypeError) as e:
        print(f"[merge] JSON 읽기 실패 {path}: {e}")
        return []
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return [x for x in items if isinstance(x, dict)]
    return []


def source_tag_from_filename(path: Path) -> str:
    """jbexport.json → JBEXPORT, my-site.json → MY_SITE."""
    stem = path.stem.strip()
    return re.sub(r"[^a-zA-Z0-9]+", "_", stem).upper().strip("_") or "UNKNOWN"


def normalize_item(item: dict, source_name: str) -> dict:
    """표준 필드 + _source/source."""
    obj = dict(item)
    tag = source_name.upper()
    obj["_source"] = tag
    obj["source"] = tag

    title = (
        obj.get("title")
        or obj.get("사업명")
        or obj.get("공고명")
        or obj.get("제목")
        or ""
    )
    obj["title"] = str(title).strip()

    url = obj.get("url") or obj.get("detail_url") or obj.get("link") or obj.get("href") or ""
    obj["url"] = str(url).strip()

    org = (
        obj.get("organization")
        or obj.get("org_name")
        or obj.get("org")
        or obj.get("agency")
        or ""
    )
    obj["organization"] = str(org).strip()

    for k in ("start_date", "end_date", "status", "description"):
        if obj.get(k) is None:
            obj[k] = ""
        else:
            obj[k] = str(obj[k]).strip()

    c = canonical_notice_source(obj)
    obj["source"] = c
    obj["_source"] = c.upper()

    return obj


def find_bizinfo_file_legacy() -> Path | None:
    candidates = [
        Path("data/bizinfo/json/bizinfo_all.json"),
        Path("data/all_jb/bizinfo_all.json"),
        Path("data/bizinfo_all.json"),
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
            return c
    return None


def enrich_bizinfo_dates(item: dict, index: int) -> dict:
    obj = dict(item)
    pr = parse_bizinfo_receipt_dates(obj)
    pb = parse_bizinfo_biz_dates(obj)
    obj["start_date"] = pr["start_date"]
    obj["end_date"] = pr["end_date"]
    obj["receipt_start"] = pr["start_date"]
    obj["receipt_end"] = pr["end_date"]
    obj["biz_start"] = pb["start_date"]
    obj["biz_end"] = pb["end_date"]
    if index < 5:
        print(
            "[bizinfo-date]",
            {
                "title": (obj.get("title") or "")[:40],
                "start_date": obj.get("start_date", ""),
                "end_date": obj.get("end_date", ""),
            },
            flush=True,
        )
    return obj


def _dedupe_key(x: dict) -> str:
    return (
        str(x.get("url") or "").strip()
        or str(x.get("detail_url") or "").strip()
        or str(x.get("id") or "").strip()
        or str(x.get("spSeq") or "").strip()
        or f"{str(x.get('title', '')).strip()}|{str(x.get('organization') or '').strip()}"
    )


def _bizinfo_stats(rows: list) -> dict:
    biz = [
        x
        for x in rows
        if isinstance(x, dict)
        and "BIZINFO" in str(x.get("_source") or x.get("source") or "").upper()
    ]
    n = len(biz)
    n_sd = sum(1 for x in biz if str(x.get("start_date") or "").strip())
    n_ed = sum(1 for x in biz if str(x.get("end_date") or "").strip())
    n_both = sum(
        1
        for x in biz
        if str(x.get("start_date") or "").strip() and str(x.get("end_date") or "").strip()
    )
    return {"total": n, "with_start": n_sd, "with_end": n_ed, "with_both": n_both}


def load_legacy_sources() -> list[tuple[list[dict], str]]:
    """raw 비었을 때만: 기존 all_jb.json + bizinfo."""
    out: list[tuple[list[dict], str]] = []
    jb = Path("data/all_jb.json")
    if jb.exists():
        rows = load_any_json(jb)
        out.append((rows, "JBEXPORT"))
        print(f"[merge][legacy] JBEXPORT ← {jb} ({len(rows)}건)")
    bp = find_bizinfo_file_legacy()
    if bp:
        rows = load_any_json(bp)
        out.append((rows, "BIZINFO"))
        print(f"[merge][legacy] BIZINFO ← {bp} ({len(rows)}건)")
    return out


def save_snapshot(all_items: list) -> Path:
    ensure_pipeline_dirs()
    snap = HISTORY_DIR / f"all_sites_{TODAY_STR}.json"
    with open(snap, "w", encoding="utf-8") as f:
        json.dump(all_items, f, ensure_ascii=False, indent=2)
    print(f"[merge] history 스냅샷: {snap}")
    return snap


def merge_all() -> list[dict]:
    ensure_pipeline_dirs()
    raw_files = discover_raw_files(RAW_DIR)
    chunks: list[tuple[list[dict], str]] = []

    if raw_files:
        for fp in raw_files:
            tag = source_tag_from_filename(fp)
            rows = load_any_json(fp)
            print(f"[merge] raw {fp.name} → source={tag} ({len(rows)}건)")
            chunks.append((rows, tag))
    else:
        print("[merge] data/raw/*.json 없음 → 레거시 경로 시도")
        chunks = load_legacy_sources()
        if not chunks:
            print("[merge] 경고: 병합할 데이터 없음")
            return []

    all_rows: list[dict] = []
    bizinfo_index = 0
    for rows, tag in chunks:
        for item in rows:
            obj = normalize_item(item, tag)
            if "BIZINFO" in tag.upper():
                obj = enrich_bizinfo_dates(obj, bizinfo_index)
                bizinfo_index += 1
            all_rows.append(obj)

    seen: set[str] = set()
    dedup: list[dict] = []
    for x in all_rows:
        k = _dedupe_key(x)
        if k and k not in seen:
            seen.add(k)
            dedup.append(x)

    print(f"[merge] 병합 후 총: {len(dedup)}건 (중복 제거 전: {len(all_rows)}건)")

    MERGED_DIR.mkdir(parents=True, exist_ok=True)
    with open(ALL_SITES_JSON, "w", encoding="utf-8") as f:
        json.dump(dedup, f, ensure_ascii=False, indent=2)
    print(f"[merge] 저장: {ALL_SITES_JSON}")

    save_snapshot(dedup)

    st = _bizinfo_stats(dedup)
    print(
        "[merge] BIZINFO date summary: "
        f"total={st['total']} start_date nonempty={st['with_start']} "
        f"end_date nonempty={st['with_end']} both={st['with_both']}"
    )

    return dedup


def main():
    merge_all()


if __name__ == "__main__":
    main()
