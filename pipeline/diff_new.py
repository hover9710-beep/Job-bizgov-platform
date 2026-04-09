import json
from pathlib import Path

TODAY_FILE = Path("data/all_sites.json")
YESTERDAY_FILE = Path("data/yesterday.json")
OUT_FILE = Path("data/new.json")


def load_json(path):
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data.get("items", [])
    return data if isinstance(data, list) else []


def main():
    today_items = load_json(TODAY_FILE)
    yesterday_items = load_json(YESTERDAY_FILE)

    # 기준: url 기반 비교
    yesterday_urls = set(item.get("url") for item in yesterday_items)

    new_items = [
        item for item in today_items
        if item.get("url") not in yesterday_urls
    ]

    print(f"[diff] today: {len(today_items)}")
    print(f"[diff] yesterday: {len(yesterday_items)}")
    print(f"[diff] new items: {len(new_items)}")

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(new_items, f, ensure_ascii=False, indent=2)

    print(f"[diff] saved: {OUT_FILE}")


if __name__ == "__main__":
    main()
