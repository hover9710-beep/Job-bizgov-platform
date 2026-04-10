import json
from datetime import date, timedelta
from pathlib import Path

TODAY_FILE = Path("data/all_sites.json")
YESTERDAY_FILE = Path("data/yesterday.json")
HISTORY_DIR = Path("data/history")
OUT_FILE = Path("data/new.json")

YESTERDAY_MIN_ITEMS = 300


def save_json(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
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


def get_item_key(x: dict) -> str:
    """make_mail.get_item_key 와 동일: url→detail_url→spSeq→id→title|organization(org_name)."""
    if not isinstance(x, dict):
        return ""
    return (
        str(x.get("url") or "").strip()
        or str(x.get("detail_url") or "").strip()
        or str(x.get("spSeq") or "").strip()
        or str(x.get("id") or "").strip()
        or f"{str(x.get('title', '')).strip()}|{str(x.get('organization') or x.get('org_name') or '').strip()}"
    )


def safe_finish(
    reason_missing: bool,
    today_items: list,
    yesterday_len: int,
):
    new_items = []
    save_json(OUT_FILE, new_items)
    if reason_missing:
        print("[diff][SAFE] yesterday file missing -> skip new detection")
    else:
        print("[diff][SAFE] yesterday invalid -> skip new detection")
    print(f"[diff] today: {len(today_items)}")
    print(f"[diff] yesterday: {yesterday_len}")
    print(f"[diff] new_items: 0")
    print("[diff] saved -> data/new.json")
    exit()


def main():
    today_str = date.today().strftime("%Y-%m-%d")
    yesterday_str = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    raw_today = load_raw(TODAY_FILE)
    if raw_today is None:
        raw_today = []
    today_items = parse_stored_items(raw_today)
    if today_items is None:
        today_items = []

    snap_today = HISTORY_DIR / f"all_sites_{today_str}.json"
    save_json(snap_today, raw_today)

    history_y = HISTORY_DIR / f"all_sites_{yesterday_str}.json"
    y_path = None
    for p in (history_y, YESTERDAY_FILE):
        if p.exists():
            y_path = p
            break

    if y_path is None:
        safe_finish(True, today_items, 0)

    raw_y = load_raw(y_path)
    if raw_y is None:
        safe_finish(False, today_items, 0)

    yesterday_items = parse_stored_items(raw_y)
    if yesterday_items is None:
        safe_finish(False, today_items, 0)

    if len(yesterday_items) < YESTERDAY_MIN_ITEMS:
        safe_finish(False, today_items, len(yesterday_items))

    y_keys = {get_item_key(x) for x in yesterday_items if get_item_key(x)}
    new_items = [
        x for x in today_items if get_item_key(x) and get_item_key(x) not in y_keys
    ]

    save_json(OUT_FILE, new_items)

    print(f"[diff] today: {len(today_items)}")
    print(f"[diff] yesterday: {len(yesterday_items)}")
    print(f"[diff] new_items: {len(new_items)}")
    print("[diff] saved -> data/new.json")


if __name__ == "__main__":
    main()
