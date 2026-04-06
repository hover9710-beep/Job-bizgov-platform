# -*- coding: utf-8 -*-
"""
pipeline/detect_deadline.py
마감 임박 공고 추출 (D-7 이내)
"""

import json
from pathlib import Path
from datetime import datetime

DATA_FILE = Path("data/raw") / (datetime.now().strftime("%Y-%m-%d") + "_all.json")
OUT_FILE  = Path("data/processed/deadline.json")

DEADLINE_DAYS = 7  # 마감 기준 (일)


def load_json(p: Path) -> list:
    if not p.exists():
        print(f"[deadline] 파일 없음: {p}")
        return []
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    # detect_new.py 와 동일하게 dict 형태 처리
    if isinstance(data, dict):
        return data.get("items", [])
    return data


def main():
    data = load_json(DATA_FILE)
    now  = datetime.now()

    deadline_items = []

    for x in data:
        end_date = x.get("end_date", "")
        if not end_date:
            continue
        try:
            d    = datetime.strptime(end_date, "%Y-%m-%d")
            diff = (d - now).days
            if 0 <= diff <= DEADLINE_DAYS:
                x["d_day"] = diff
                deadline_items.append(x)
        except ValueError:
            continue

    deadline_items.sort(key=lambda x: x.get("d_day", 99))

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    output = {
        "date":  now.strftime("%Y-%m-%d"),
        "count": len(deadline_items),
        "items": deadline_items,
    }

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[deadline] 마감임박 {len(deadline_items)}건 → {OUT_FILE}")
    for item in deadline_items[:5]:
        print(f"  D-{item['d_day']} {item.get('title','')[:30]}")


if __name__ == "__main__":
    main()
