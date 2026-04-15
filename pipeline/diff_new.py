# -*- coding: utf-8 -*-
"""
오늘 merged/all_sites.json vs 전일(또는 최근) 스냅샷 비교 → merged/new.json

- 재크롤링 없음
- SAFE 모드: 어제본 없거나 비정상이면 new.json = []
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pipeline.data_paths import (
    ALL_SITES_JSON,
    HISTORY_DIR,
    NEW_JSON,
    ensure_pipeline_dirs,
)

TODAY_FILE = ALL_SITES_JSON
OUT_FILE = NEW_JSON
YESTERDAY_FILE = Path("data/yesterday.json")
YESTERDAY_MIN_ITEMS = 300


def get_item_key(x: dict) -> str:
    if not isinstance(x, dict):
        return ""
    url = str(x.get("url") or x.get("detail_url") or x.get("link") or "").strip()
    if url:
        return url
    src = str(x.get("source") or x.get("_source") or "").strip().lower()
    title = str(x.get("title") or "").strip()
    org = str(x.get("organization") or x.get("org") or "").strip()
    end_date = str(x.get("end_date") or x.get("receipt_end") or "").strip()
    if src or title or org or end_date:
        return "|".join([src, title, org, end_date])
    return ""


def save_json(path: Path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_raw(path: Path):
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def parse_stored_items(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        items = data.get("items", [])
        return items if isinstance(items, list) else None
    return None


def get_latest_snapshot_before_today(history_dir: Path) -> Path | None:
    """history/all_sites_YYYY-MM-DD.json 중 오늘보다 이전 날짜 중 가장 최근 파일."""
    today = date.today()
    best_d: date | None = None
    best_p: Path | None = None
    if not history_dir.is_dir():
        return None
    for p in history_dir.glob("all_sites_*.json"):
        m = re.match(r"all_sites_(\d{4}-\d{2}-\d{2})\.json", p.name)
        if not m:
            continue
        d = datetime.strptime(m.group(1), "%Y-%m-%d").date()
        if d >= today:
            continue
        if best_d is None or d > best_d:
            best_d = d
            best_p = p
    return best_p


def safe_finish(
    reason_missing: bool,
    today_items: list,
    yesterday_len: int,
):
    new_items = []
    ensure_pipeline_dirs()
    save_json(OUT_FILE, new_items)
    if reason_missing:
        print("[diff][SAFE] baseline 없음 -> skip new detection")
    else:
        print("[diff][SAFE] baseline 비정상 -> skip new detection")
    print(f"[diff] today: {len(today_items)}")
    print(f"[diff] baseline: {yesterday_len}")
    print(f"[diff] new_items: 0")
    print(f"[diff] saved -> {OUT_FILE}")
    sys.exit(0)


def main():
    yesterday_str = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")

    ensure_pipeline_dirs()

    raw_today = load_raw(TODAY_FILE)
    if raw_today is None:
        raw_today = []
    today_items = parse_stored_items(raw_today)
    if today_items is None:
        today_items = []

    # 오늘 스냅샷은 merge_sources에서만 기록 (단일 소스)

    baseline_path = get_latest_snapshot_before_today(HISTORY_DIR)
    if baseline_path is None:
        history_y = HISTORY_DIR / f"all_sites_{yesterday_str}.json"
        for p in (history_y, YESTERDAY_FILE):
            if p.exists():
                baseline_path = p
                break

    if baseline_path is None:
        safe_finish(True, today_items, 0)

    raw_b = load_raw(baseline_path)
    if raw_b is None:
        safe_finish(False, today_items, 0)

    baseline_items = parse_stored_items(raw_b)
    if baseline_items is None:
        safe_finish(False, today_items, 0)

    if len(baseline_items) < YESTERDAY_MIN_ITEMS:
        safe_finish(False, today_items, len(baseline_items))

    y_keys = {get_item_key(x) for x in baseline_items if get_item_key(x)}
    new_items = [
        x for x in today_items if get_item_key(x) and get_item_key(x) not in y_keys
    ]

    save_json(OUT_FILE, new_items)

    print(f"[diff] today: {len(today_items)}")
    print(f"[diff] baseline: {len(baseline_items)} ({baseline_path})")
    print(f"[diff] new_items: {len(new_items)}")
    print(f"[diff] saved -> {OUT_FILE}")


if __name__ == "__main__":
    main()
