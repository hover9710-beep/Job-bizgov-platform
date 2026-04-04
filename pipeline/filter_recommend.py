# -*- coding: utf-8 -*-
"""
서버 측 필터·추천 후보 (merge 결과 JSON 기준).

- 수집 단계에서 걸러지지 않은 전체 데이터를 읽고,
  환경변수 등으로 필터 키워드를 주면 title·description·organization 합친 문자열에
  부분 일치(`is_match`)로 축소.

실행(루트):
  py pipeline/filter_recommend.py
  FILTER_KEYWORDS=중소기업,수출 py pipeline/filter_recommend.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ALL_JB = ROOT / "data" / "all_jb" / "all_jb.json"
OUT_DIR = ROOT / "data" / "filtered"
OUT_JSON = OUT_DIR / "recommended.json"


def load_merged() -> List[Dict[str, Any]]:
    if not ALL_JB.exists():
        return []
    try:
        data = json.loads(ALL_JB.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, dict)]


def is_match(notice: dict, keywords: list[str]) -> bool:
    """title + description + organization 중 keyword 하나라도 포함되면 True"""
    title = (
        notice.get("title", "")
        or notice.get("공고제목", "")
        or ""
    )
    description = (
        notice.get("description", "")
        or notice.get("content", "")
        or notice.get("본문", "")
        or ""
    )
    organization = (
        notice.get("organization", "")
        or notice.get("org", "")
        or notice.get("기관", "")
        or ""
    )

    text = (title + " " + description + " " + organization).lower()
    return any((kw or "").lower() in text for kw in keywords if kw)


def filter_items(
    items: List[Dict[str, Any]],
    keywords: List[str],
) -> List[Dict[str, Any]]:
    if not keywords:
        return list(items)
    return [it for it in items if is_match(it, keywords)]


def main() -> int:
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass

    raw = os.environ.get("FILTER_KEYWORDS", "").strip()
    keywords = [x.strip() for x in raw.split(",") if x.strip()] if raw else []

    items = load_merged()
    print(f"[filter_recommend] source: {ALL_JB}")
    print(f"[filter_recommend] loaded: {len(items)}건")

    filtered = filter_items(items, keywords)
    if keywords:
        print(f"[filter_recommend] FILTER_KEYWORDS={keywords!r} → {len(filtered)}건")
    else:
        print("[filter_recommend] FILTER_KEYWORDS 없음 → 필터 생략(전체 통과)")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(
        json.dumps(filtered, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[filter_recommend] saved: {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
