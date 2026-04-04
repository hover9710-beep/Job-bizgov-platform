"""
today.json / yesterday.json 을 title 기준으로 비교해 신규 공고만 반환.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Set

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_TODAY = BASE_DIR / "data" / "today.json"
DEFAULT_YESTERDAY = BASE_DIR / "data" / "yesterday.json"


def _normalize_title(value: Any) -> str:
    return str(value or "").strip()


def _titles_from_yesterday(items: List[Dict[str, Any]]) -> Set[str]:
    keys = (
        "title",
        "공고제목",
        "사업명",
        "js_title",
        "subject",
        "name",
    )
    seen: Set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        t = ""
        for k in keys:
            t = _normalize_title(item.get(k))
            if t:
                break
        if t:
            seen.add(t)
    return seen


def _load_list(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    return []


def compare_new(
    today_path: Path | str | None = None,
    yesterday_path: Path | str | None = None,
) -> List[Dict[str, Any]]:
    """
    yesterday에 없는 title을 가진 today 항목만 반환.

    title 후보 키: title, 공고제목, 사업명, js_title, subject, name
    (첫 번째로 비어 있지 않은 값 사용)
    """
    today_p = Path(today_path) if today_path else DEFAULT_TODAY
    yesterday_p = Path(yesterday_path) if yesterday_path else DEFAULT_YESTERDAY

    if not today_p.is_absolute():
        today_p = BASE_DIR / today_p
    if not yesterday_p.is_absolute():
        yesterday_p = BASE_DIR / yesterday_p

    today_items = _load_list(today_p)
    yesterday_items = _load_list(yesterday_p)
    old_titles = _titles_from_yesterday(yesterday_items)

    keys = (
        "title",
        "공고제목",
        "사업명",
        "js_title",
        "subject",
        "name",
    )
    new_list: List[Dict[str, Any]] = []
    for item in today_items:
        title = ""
        for k in keys:
            title = _normalize_title(item.get(k))
            if title:
                break
        if not title:
            continue
        if title in old_titles:
            continue
        new_list.append(item)

    return new_list


def compare_title_snapshots(
    today_path: Path | str | None = None,
    yesterday_path: Path | str | None = None,
) -> List[Dict[str, Any]]:
    """daily_run 용 별칭: today.json / yesterday.json 제목 기준 신규만 반환."""
    return compare_new(today_path, yesterday_path)


if __name__ == "__main__":
    out = compare_new()
    print(json.dumps(out, ensure_ascii=False, indent=2))
